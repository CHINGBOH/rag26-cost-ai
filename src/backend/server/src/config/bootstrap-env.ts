import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const serverConfigDir = path.resolve(currentDir, '../../config');
const repoRootEnvPath = path.resolve(currentDir, '../../../../../.env');

if (!process.env.NODE_CONFIG_DIR) {
  process.env.NODE_CONFIG_DIR = serverConfigDir;
}

dotenv.config({
  path: repoRootEnvPath,
  override: false,
});
