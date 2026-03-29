import { build } from 'esbuild'
import { rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

export async function runBundledTest(options) {
  const { webDir, entryFile, tempPrefix } = options
  const tempDir = path.join(os.tmpdir(), `${tempPrefix}-${process.pid}`)
  const outfile = path.join(tempDir, 'bundle.mjs')

  try {
    await build({
      absWorkingDir: webDir,
      entryPoints: [entryFile],
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
}
