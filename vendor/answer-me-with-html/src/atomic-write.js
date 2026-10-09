import { openSync, writeFileSync, fsyncSync, closeSync, renameSync, unlinkSync, lstatSync, chmodSync } from 'node:fs';
import { dirname, basename, join } from 'node:path';
import { randomUUID } from 'node:crypto';

export function atomicWrite(file, content, { rename = renameSync } = {}) {
  let mode = 0o600;
  try {
    const stat = lstatSync(file);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('Output must be a regular file, not a symlink or directory');
    mode = stat.mode & 0o777;
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  const temporary = join(dirname(file), `.${basename(file)}.${randomUUID()}.tmp`);
  let fd;
  try {
    fd = openSync(temporary, 'wx', mode);
    writeFileSync(fd, content);
    fsyncSync(fd);
    closeSync(fd);
    fd = undefined;
    chmodSync(temporary, mode);
    rename(temporary, file);
  } finally {
    if (fd !== undefined) closeSync(fd);
    try { unlinkSync(temporary); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
}
