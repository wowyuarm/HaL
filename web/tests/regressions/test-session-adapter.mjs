import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { runBundledTest } from './support/run-bundled-test.mjs'

const scriptPath = fileURLToPath(import.meta.url)
const scriptDir = path.dirname(scriptPath)
const webDir = path.resolve(scriptDir, '../..')

await runBundledTest({
  webDir,
  entryFile: path.join(scriptDir, 'test-session-adapter.entry.ts'),
  tempPrefix: 'hal-web-session-adapter',
})
