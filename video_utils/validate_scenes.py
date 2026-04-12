#!/usr/bin/env python3
"""Validate Manim CE scenes: overlapping text and out-of-bounds elements.

Two modes:
  Fast (default)  — skip_animations, checks text-vs-text overlaps + all OOB. Seconds.
  Render (--render) — renders 480p15, extracts 8 frames per scene into contact sheets.
"""

import argparse
import importlib.util
import subprocess
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
from manim import *

FRAME_W = config.frame_width
FRAME_H = config.frame_height
HALF_W = FRAME_W / 2
HALF_H = FRAME_H / 2
# Tighter safe bounds per skill spec
SAFE_X = 6.5
SAFE_Y = 3.5
OOB_TOL = 0.1
OVERLAP_AREA_THRESHOLD = 0.10  # >10% area overlap of smaller element

# Structural types to IGNORE for text-vs-text overlap checks
STRUCTURAL_TYPES = (
    NumberPlane, Axes, NumberLine, Arrow, Line, DashedLine, DashedVMobject,
    Dot, Circle, Rectangle, RoundedRectangle, Square, Triangle, Polygon,
    Ellipse, Annulus, Sector, SurroundingRectangle, Cross,
)
# Readable types to CHECK for overlaps
READABLE_TYPES = (Text, MathTex, Tex, Paragraph)
# Line-like types that should NOT cross through text
LINE_TYPES = (Arrow, Line, DashedLine, FunctionGraph)


def bbox(mob):
    ul = mob.get_critical_point(UL)
    dr = mob.get_critical_point(DR)
    return ul[0], dr[1], dr[0], ul[1]  # x_min, y_min, x_max, y_max


def overlap_area(a, b):
    """Return overlap area between two bboxes, or 0 if no overlap."""
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    if dx <= 0 or dy <= 0:
        return 0.0
    return dx * dy


def box_area(bb):
    return max(0, bb[2] - bb[0]) * max(0, bb[3] - bb[1])


def is_oob(bb):
    return (bb[0] < -SAFE_X - OOB_TOL or bb[2] > SAFE_X + OOB_TOL or
            bb[1] < -SAFE_Y - OOB_TOL or bb[3] > SAFE_Y + OOB_TOL)


def is_readable(mob):
    """Check if mob or any ancestor is a readable type."""
    return isinstance(mob, READABLE_TYPES)


def mob_label(mob):
    if isinstance(mob, Text):
        return f'Text("{mob.text[:40]}")'
    if isinstance(mob, MathTex):
        s = mob.tex_string[:40] if hasattr(mob, "tex_string") else str(mob.tex_strings[:1])
        return f'MathTex("{s}")'
    if isinstance(mob, Tex):
        return f'Tex({str(mob.tex_strings[:1])[:40]})'
    cls = type(mob).__name__
    return f"{cls}@({mob.get_center()[0]:.1f},{mob.get_center()[1]:.1f})"


def get_all_readable(scene):
    """Collect all readable mobjects (Text, MathTex, Tex) from the scene."""
    results = []
    for mob in scene.mobjects:
        _collect_readable(mob, results)
    return results


def _collect_readable(mob, out):
    if is_readable(mob) and (mob.has_points() or len(mob.submobjects) > 0):
        bb = bbox(mob)
        if bb[2] - bb[0] > 0.01 and bb[3] - bb[1] > 0.01:
            out.append(mob)
            return  # don't recurse into sub-glyphs
    for sub in mob.submobjects:
        _collect_readable(sub, out)


def get_all_mobjects(scene):
    """Collect all top-level mobjects for OOB checking."""
    results = []
    for mob in scene.mobjects:
        if mob.has_points() or len(mob.submobjects) > 0:
            bb = bbox(mob)
            if bb[2] - bb[0] > 0.01 and bb[3] - bb[1] > 0.01:
                results.append(mob)
    return results


def get_all_lines(scene):
    """Collect all line-like mobjects (Arrow, Line, FunctionGraph) from the scene."""
    results = []
    for mob in scene.mobjects:
        _collect_lines(mob, results)
    return results


def _collect_lines(mob, out):
    if isinstance(mob, LINE_TYPES) and (mob.has_points() or len(mob.submobjects) > 0):
        bb = bbox(mob)
        if bb[2] - bb[0] > 0.01 or bb[3] - bb[1] > 0.01:  # lines can be thin in one dim
            out.append(mob)
    for sub in mob.submobjects:
        _collect_lines(sub, out)


class ValidatingScene(Scene):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._snapshots = []
        self._anim_count = 0

    def play(self, *args, **kwargs):
        super().play(*args, **kwargs)
        self._anim_count += 1
        self._capture(f"play_{self._anim_count}")

    def wait(self, *args, **kwargs):
        self._capture(f"wait_{self._anim_count}")
        super().wait(*args, **kwargs)

    def _capture(self, label):
        readables = get_all_readable(self)
        all_mobs = get_all_mobjects(self)
        lines = get_all_lines(self)
        self._snapshots.append((label, readables, all_mobs, lines))


def _make_validating_cls(scene_cls):
    """Create a ValidatingScene that inherits from the scene's actual base class."""
    # Find the scene's base class (e.g. SyncedScene, Scene)
    bases = [b for b in scene_cls.__mro__ if issubclass(b, Scene) and b is not scene_cls]
    base = bases[0] if bases else Scene

    # Dynamically build a validating mixin that adds snapshot capture
    class _Validator(base):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._snapshots = []
            self._anim_count = 0

        def play(self, *args, **kwargs):
            super().play(*args, **kwargs)
            self._anim_count += 1
            self._capture(f"after_play_{self._anim_count}")

        def wait(self, *args, **kwargs):
            self._capture(f"at_wait_{self._anim_count}")
            super().wait(*args, **kwargs)

        def _capture(self, label):
            readables = get_all_readable(self)
            all_mobs = get_all_mobjects(self)
            lines = get_all_lines(self)
            self._snapshots.append((label, readables, all_mobs, lines))

    return type(f"V_{scene_cls.__name__}", (_Validator,), {"construct": scene_cls.construct})


def validate_scene_class(scene_cls, verbose=False):
    issues = []
    validating_cls = _make_validating_cls(scene_cls)
    print(f"\n{'='*60}\n  Checking: {scene_cls.__name__}\n{'='*60}")
    try:
        scene = validating_cls(skip_animations=True)
        scene.render()
    except Exception as e:
        print(f"  CRASH: {e}")
        import traceback; traceback.print_exc()
        return [f"CRASH: {e}"]

    for snap_label, readables, all_mobs, lines in scene._snapshots:
        # OOB check on ALL mobjects
        for mob in all_mobs:
            bb = bbox(mob)
            if is_oob(bb):
                msg = (f"[OOB] {snap_label}: {mob_label(mob)}  "
                       f"bbox=({bb[0]:.2f},{bb[1]:.2f})->({bb[2]:.2f},{bb[3]:.2f})")
                if msg not in issues:
                    issues.append(msg)

        # Text-exceeds-container check: text whose center is inside a shape
        # but whose bbox extends beyond the shape boundary.
        # Check BOTH within VGroups AND globally (text and container may not be grouped).
        CONTAINER_TYPES = (Circle, Rectangle, RoundedRectangle, Square, Ellipse)

        # Collect all container shapes from the scene (recursively)
        containers = []
        def _collect_containers(mob):
            if isinstance(mob, CONTAINER_TYPES):
                cbb = bbox(mob)
                if (cbb[2] - cbb[0]) > 0.5 and (cbb[3] - cbb[1]) > 0.5:
                    containers.append(mob)
            for sub in mob.submobjects:
                _collect_containers(sub)
        for mob in scene._original_mobjects if hasattr(scene, '_original_mobjects') else all_mobs:
            _collect_containers(mob)

        # Check every readable text against every container
        for container in containers:
            cbb = bbox(container)
            c_w = cbb[2] - cbb[0]
            c_h = cbb[3] - cbb[1]
            for txt in readables:
                tbb = bbox(txt)
                tc = txt.get_center()
                # Check if text overlaps with container significantly
                # (center inside OR >30% of text area overlaps the container)
                oa = overlap_area(tbb, cbb)
                ta = box_area(tbb)
                center_inside = (cbb[0] <= tc[0] <= cbb[2] and cbb[1] <= tc[1] <= cbb[3])
                significant_overlap = ta > 0 and (oa / ta) > 0.3
                if not (center_inside or significant_overlap):
                    continue
                # Check horizontal overflow
                exceed_left = max(0, cbb[0] - tbb[0])
                exceed_right = max(0, tbb[2] - cbb[2])
                exceed_x = exceed_left + exceed_right
                # Check vertical overflow
                exceed_top = max(0, tbb[3] - cbb[3])
                exceed_bottom = max(0, cbb[1] - tbb[1])
                exceed_y = exceed_top + exceed_bottom
                if exceed_x > c_w * 0.05 or exceed_y > c_h * 0.05:
                    direction = "horizontally" if exceed_x > exceed_y else "vertically"
                    exceed = max(exceed_x, exceed_y)
                    msg = (f"[TEXT-OVERFLOW] {snap_label}: {mob_label(txt)} "
                           f"overflows container {direction} by {exceed:.2f} units")
                    if msg not in issues:
                        issues.append(msg)

        # Overlap check only on READABLE pairs (Text vs Text)
        for m1, m2 in combinations(readables, 2):
            bb1, bb2 = bbox(m1), bbox(m2)
            oa = overlap_area(bb1, bb2)
            if oa <= 0:
                continue
            smaller_area = min(box_area(bb1), box_area(bb2))
            if smaller_area <= 0:
                continue
            pct = oa / smaller_area
            if pct >= OVERLAP_AREA_THRESHOLD:
                msg = (f"[OVERLAP {pct:.0%}] {snap_label}: "
                       f"{mob_label(m1)} <-> {mob_label(m2)}")
                if msg not in issues:
                    issues.append(msg)

        # Line-vs-text collision: arrows, lines, curves crossing through text
        for line_mob in lines:
            lbb = bbox(line_mob)
            for txt in readables:
                tbb = bbox(txt)
                oa = overlap_area(lbb, tbb)
                if oa <= 0:
                    continue
                txt_area = box_area(tbb)
                if txt_area <= 0:
                    continue
                pct = oa / txt_area
                if pct >= 0.15:  # line covers >15% of the text area
                    line_type = type(line_mob).__name__
                    msg = (f"[LINE-CROSS {pct:.0%}] {snap_label}: "
                           f"{line_type} crosses through {mob_label(txt)}")
                    if msg not in issues:
                        issues.append(msg)

    if verbose and scene._snapshots:
        _, readables, all_mobs, lines = scene._snapshots[-1]
        print(f"\n  Final frame — {len(readables)} readable, {len(all_mobs)} total, {len(lines)} lines:")
        for mob in readables:
            bb = bbox(mob)
            flag = " OOB!" if is_oob(bb) else ""
            print(f"    {mob_label(mob):50s} ({bb[0]:+.2f},{bb[1]:+.2f})->({bb[2]:+.2f},{bb[3]:+.2f}){flag}")

    crashes = sum(1 for i in issues if "CRASH" in i)
    oob_n = sum(1 for i in issues if "[OOB]" in i)
    ovl_n = sum(1 for i in issues if "[OVERLAP" in i)
    overflow_n = sum(1 for i in issues if "[TEXT-OVERFLOW" in i)
    linecross_n = sum(1 for i in issues if "[LINE-CROSS" in i)
    if issues:
        print(f"\n  {oob_n} OOB, {ovl_n} overlaps, {overflow_n} overflows, {linecross_n} line-crosses, {crashes} crashes:")
        for i in issues:
            print(f"    {i}")
    else:
        print("  ✓ No issues found")
    return issues


def capture_segment_screenshots(filepath, scene_name=None):
    """Capture the final frame of each segment (right before FadeOut(Group(*))).

    Uses skip_animations=True so it's fast (<1s per scene, no video rendering).
    Saves PNGs to videos/review/<video_stem>/<SceneName>_seg_NN.png.
    Returns list of saved PNG paths for visual inspection.
    """
    from PIL import Image

    path = Path(filepath).resolve()
    scenes = load_scenes(str(path))
    if scene_name:
        scenes = {scene_name: scenes[scene_name]}

    review_dir = path.resolve().parents[1] / "review" / path.stem
    review_dir.mkdir(parents=True, exist_ok=True)

    all_pngs = []

    for name, cls in scenes.items():
        # Find the scene's actual base class (e.g. SyncedScene)
        bases = [b for b in cls.__mro__ if issubclass(b, Scene) and b is not cls]
        base = bases[0] if bases else Scene

        class ScreenshotScene(base):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self._shot_count = 0
                self._saved = []

            def play(self, *args, **kwargs):
                # Capture BEFORE any FadeOut(Group(*)) call
                is_fadeout_all = (
                    len(args) == 1
                    and isinstance(args[0], FadeOut)
                    and isinstance(args[0].mobject, Group)
                )
                if is_fadeout_all and self.mobjects:
                    self._shot_count += 1
                    frame = self.camera.pixel_array
                    img = Image.fromarray(frame)
                    fname = f"{name}_seg_{self._shot_count:02d}.png"
                    out = review_dir / fname
                    img.save(str(out))
                    self._saved.append(out)
                super().play(*args, **kwargs)

        screenshot_cls = type(f"SS_{name}", (ScreenshotScene,),
                              {"construct": cls.construct})

        config.quality = "low_quality"
        config.save_last_frame = False
        config.write_to_movie = False

        try:
            scene = screenshot_cls(skip_animations=True)
            scene.render()
            for p in scene._saved:
                print(f"    ✓ {p.name}")
                all_pngs.append(p)
        except Exception as e:
            print(f"    CRASH: {e}")

    print(f"\n  {len(all_pngs)} screenshots saved to: {review_dir}")
    return all_pngs


def render_contact_sheets(filepath, scene_name=None):
    """Render scenes at 480p15 and extract 8-frame contact sheets."""
    path = Path(filepath).resolve()
    scenes = load_scenes(str(path))
    if scene_name:
        scenes = {scene_name: scenes[scene_name]}

    # Derive video number from filename
    vid_num = path.stem.replace("video", "")
    review_dir = path.resolve().parents[1] / "review" / f"video{vid_num}"
    review_dir.mkdir(parents=True, exist_ok=True)

    proj_root = path.resolve().parents[1]

    for name in scenes:
        print(f"  Rendering {name} at 480p15...")
        cmd = [
            sys.executable, "-m", "manim", "render",
            "-ql", "--fps", "15", "--disable_caching",
            str(path), name,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(proj_root))
        if result.returncode != 0:
            print(f"    RENDER FAILED:\n{result.stderr[-500:]}")
            continue

        # Find rendered video
        media_dir = proj_root.parent / "media" / "videos" / path.stem / "480p15"
        vid_file = media_dir / f"{name}.mp4"
        if not vid_file.exists():
            # Try alternate paths
            for p in media_dir.parent.rglob(f"{name}.mp4"):
                vid_file = p
                break

        if not vid_file.exists():
            print(f"    Could not find rendered video for {name}")
            continue

        # Extract 8 frames and tile into contact sheet
        sheet = review_dir / f"{name}.png"
        # Get duration
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(vid_file)],
            capture_output=True, text=True
        )
        duration = float(probe.stdout.strip())
        # Extract 8 frames at even intervals
        interval = duration / 8
        filter_str = f"select='lt(mod(t\\,{interval:.2f})\\,0.1)',scale=640:360,tile=4x2"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(vid_file),
             "-vf", filter_str, "-frames:v", "1", str(sheet)],
            capture_output=True
        )
        if sheet.exists():
            print(f"    ✓ Contact sheet: {sheet}")
        else:
            print(f"    ✗ Failed to create contact sheet")


def load_scenes(filepath):
    path = Path(filepath).resolve()
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)
    return {n: getattr(mod, n) for n in dir(mod)
            if isinstance(getattr(mod, n), type)
            and issubclass(getattr(mod, n), Scene)
            and getattr(mod, n) is not Scene
            and "construct" in getattr(mod, n).__dict__}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("scene", nargs="?")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--render", action="store_true",
                    help="Render at 480p15 and generate contact sheet PNGs")
    ap.add_argument("--screenshots", action="store_true",
                    help="Capture segment-end screenshots (<1s/scene, no video render)")
    args = ap.parse_args()

    if args.screenshots:
        print("=== Screenshot Mode: capturing segment-end frames ===")
        capture_segment_screenshots(args.file, args.scene)
    elif args.render:
        print("=== Render Mode: generating contact sheets ===")
        render_contact_sheets(args.file, args.scene)
    else:
        print("=== Fast Mode: text overlap + OOB check ===")
        scenes = load_scenes(args.file)
        if args.scene:
            scenes = {args.scene: scenes[args.scene]}
        total = 0
        for name, cls in scenes.items():
            total += len(validate_scene_class(cls, args.verbose))
        print(f"\nTOTAL: {total} issues across {len(scenes)} scenes")
        sys.exit(1 if total else 0)
