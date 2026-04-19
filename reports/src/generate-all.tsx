/**
 * 主生成脚本 - 同时生成专业版和通俗版报告
 */

import * as fs from 'fs';
import * as path from 'path';

const OUTPUT_DIR = path.join(__dirname, '../');

console.log('🚀 开始生成 LangChain RAG 架构分析报告...\n');

// 生成专业版
const { default: generateProfessional } = await import('./report-generator.tsx');
// generateProfessional();

// 生成通俗版
const { default: generateFolk } = await import('./folk-report-generator.tsx');
// generateFolk();

console.log('\n📊 报告生成完成！');
console.log('\n生成的文件：');
console.log('  1. LangChain-RAG-Report-Professional.md (专业版)');
console.log('  2. LangChain-RAG-Report-Folk.md (通俗版)');
console.log('\n祝您阅读愉快！');
