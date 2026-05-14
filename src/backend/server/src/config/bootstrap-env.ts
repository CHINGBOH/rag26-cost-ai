import dotenv from 'dotenv';
import path from 'path';

const currentDir = __dirname;
const serverConfigDir = path.resolve(currentDir, '../../config');
const repoRootEnvPath = path.resolve(currentDir, '../../../../../.env');

if (!process.env.NODE_CONFIG_DIR) {
  process.env.NODE_CONFIG_DIR = serverConfigDir;
}

dotenv.config({
  path: repoRootEnvPath,
  override: false,
});
