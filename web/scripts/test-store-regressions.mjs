import { build } from 'esbuild'
import { rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const scriptPath = fileURLToPath(import.meta.url)
const scriptDir = path.dirname(scriptPath)
const webDir = path.resolve(scriptDir, '..')
const tempDir = path.join(os.tmpdir(), `hal-web-store-regressions-${process.pid}`)
const outfile = path.join(tempDir, 'bundle.mjs')

try {
  await build({
    absWorkingDir: webDir,
    entryPoints: [path.join(scriptDir, 'test-store-regressions.entry.ts')],
    bundle: true,
    format: 'esm',
    outfile,
    platform: 'node',
    sourcemap: 'inline',
    tsconfig: path.join(webDir, 'tsconfig.json'),
    logLevel: 'silent',
  })

  await import(pathToFileURL(outfile).href)
} finally {
  await rm(tempDir, { recursive: true, force: true })
}
