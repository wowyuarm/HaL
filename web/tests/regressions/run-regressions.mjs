import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptPath = fileURLToPath(import.meta.url)
const scriptDir = path.dirname(scriptPath)
const webDir = path.resolve(scriptDir, '../..')

const TEST_COMMANDS = [
  { label: 'store regressions', script: 'test:store' },
  { label: 'process preview', script: 'test:process' },
  { label: 'session adapter', script: 'test:adapter' },
]

for (const testCommand of TEST_COMMANDS) {
  await runScript(testCommand)
}

async function runScript(testCommand) {
  console.log(`\n==> ${testCommand.label}`)

  await new Promise((resolve, reject) => {
    const child = spawn('npm', ['run', testCommand.script], {
      cwd: webDir,
      stdio: 'inherit',
    })

    child.on('exit', (code) => {
      if (code === 0) {
        resolve()
        return
      }
      reject(new Error(`${testCommand.script} exited with code ${code ?? 'unknown'}`))
    })
    child.on('error', reject)
  })
}
