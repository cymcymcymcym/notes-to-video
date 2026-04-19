#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");

const PKG_ROOT = path.resolve(__dirname, "..");
const HOME = os.homedir();

const SKILL_SRC = path.join(PKG_ROOT, "skills", "notes-to-video");
const SKILL_DST = path.join(HOME, ".claude", "skills", "notes-to-video");

const UTILS_SRC = path.join(PKG_ROOT, "video_utils");
const UTILS_DST = path.join(HOME, "tools", "video_utils");

function printHelp() {
  console.log(`notes-to-video — install the Claude Code skill

Usage:
  npx notes-to-video           Install skill + video_utils
  npx notes-to-video --help    Show this message

What it does:
  ${SKILL_SRC}
    → ${SKILL_DST}
  ${UTILS_SRC}
    → ${UTILS_DST}

Re-running upgrades in place (overwrites the destinations).`);
}

function install(src, dst, label) {
  if (!fs.existsSync(src)) {
    console.error(`  ✗ missing source: ${src}`);
    process.exit(1);
  }
  const existed = fs.existsSync(dst);
  if (existed) {
    fs.rmSync(dst, { recursive: true, force: true });
  }
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.cpSync(src, dst, { recursive: true });
  console.log(`  ✓ ${label} → ${dst}${existed ? " (replaced)" : ""}`);
}

function main() {
  const args = process.argv.slice(2);
  if (args.includes("--help") || args.includes("-h")) {
    printHelp();
    return;
  }

  console.log("Installing notes-to-video...\n");
  install(SKILL_SRC, SKILL_DST, "skill");
  install(UTILS_SRC, UTILS_DST, "video_utils");

  console.log(`
Installed.

Next steps:
  1. Create the Python venv (one-time, shared across projects):
       python3 -m venv ~/tools/.venv
       ~/tools/.venv/bin/pip install manim edge-tts pydub faster-whisper
       # Optional: chatterbox-tts (local voice cloning), torch with CUDA
  2. Add API keys for cloud TTS (optional):
       mkdir -p ~/tools/credentials
       printf 'MINIMAX_API_KEY=...\\nMINIMAX_GROUP_ID=...\\nOPENAI_API_KEY=...\\n' \\
         > ~/tools/credentials/.env
  3. In your project, open Claude Code and ask:
       "make a 3b1b-style video about <topic>"
     or point it at a notes file:
       "make a video from ~/Documents/notes.pdf"
`);
}

try {
  main();
} catch (err) {
  console.error(`\nInstall failed: ${err.message}`);
  process.exit(1);
}
