import { cp, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { basename, dirname, extname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const currentDir = dirname(fileURLToPath(import.meta.url));
const docsRoot = resolve(currentDir, '../../docs');
const outputRoot = resolve(currentDir, '../public/help-docs');

const CATEGORY_ORDER = [
  '00_共通',
  '01_要件定義',
  '02_設計',
  '03_運用',
  '04_利用ガイド',
];

const toPosixPath = (value) => value.split(sep).join('/');

const toCategoryLabel = (key) => {
  if (key === '00_共通') {
    return '共通';
  }
  return key.replace(/^\d+_/, '').replace(/_/g, ' ').trim() || 'その他';
};

const extractTitle = (markdown, fallback) => {
  const heading = markdown.match(/^#\s+(.+)$/m);
  if (heading?.[1]) {
    return heading[1].trim();
  }
  return fallback;
};

const extractSummary = (markdown) => {
  const lines = markdown.split(/\r?\n/);
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#') || line.startsWith('```')) {
      continue;
    }
    if (/^[-*]\s+/.test(line) || /^\d+\.\s+/.test(line)) {
      continue;
    }
    return line.length > 140 ? `${line.slice(0, 140)}...` : line;
  }
  return '';
};

const encodePath = (value) => {
  return value
    .split('/')
    .map((segment) => encodeURIComponent(segment))
    .join('/');
};

const listMarkdownFiles = async (dir) => {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const absolutePath = join(dir, entry.name);

    if (entry.isDirectory()) {
      const nested = await listMarkdownFiles(absolutePath);
      files.push(...nested);
      continue;
    }

    if (entry.isFile() && extname(entry.name).toLowerCase() === '.md') {
      files.push(absolutePath);
    }
  }

  return files;
};

const sortDocs = (left, right) => {
  const leftCategory = CATEGORY_ORDER.indexOf(left.category_key);
  const rightCategory = CATEGORY_ORDER.indexOf(right.category_key);

  const leftRank = leftCategory === -1 ? Number.MAX_SAFE_INTEGER : leftCategory;
  const rightRank = rightCategory === -1 ? Number.MAX_SAFE_INTEGER : rightCategory;

  if (leftRank !== rightRank) {
    return leftRank - rightRank;
  }

  return left.source_path.localeCompare(right.source_path, 'ja');
};

const main = async () => {
  await rm(outputRoot, { recursive: true, force: true });
  await mkdir(outputRoot, { recursive: true });

  const markdownFiles = await listMarkdownFiles(docsRoot);
  const docs = [];

  for (const sourceFile of markdownFiles) {
    const relativePath = toPosixPath(relative(docsRoot, sourceFile));
    const outputFile = resolve(outputRoot, relativePath);
    const categoryKey = relativePath.includes('/') ? relativePath.split('/')[0] : '00_共通';

    await mkdir(dirname(outputFile), { recursive: true });
    await cp(sourceFile, outputFile);

    const markdown = await readFile(sourceFile, 'utf-8');
    docs.push({
      id: `docs/${relativePath}`,
      source_path: `docs/${relativePath}`,
      web_path: relativePath,
      web_path_encoded: encodePath(relativePath),
      category_key: categoryKey,
      category_label: toCategoryLabel(categoryKey),
      title: extractTitle(markdown, basename(relativePath, '.md')),
      summary: extractSummary(markdown),
    });
  }

  docs.sort(sortDocs);

  const categories = [];
  const categoryMap = new Map();

  for (const doc of docs) {
    const existing = categoryMap.get(doc.category_key);
    const payload = {
      id: doc.id,
      title: doc.title,
      summary: doc.summary,
      source_path: doc.source_path,
      web_path: doc.web_path,
      web_path_encoded: doc.web_path_encoded,
    };

    if (existing) {
      existing.items.push(payload);
      continue;
    }

    const next = {
      key: doc.category_key,
      label: doc.category_label,
      items: [payload],
    };
    categories.push(next);
    categoryMap.set(doc.category_key, next);
  }

  await writeFile(
    resolve(outputRoot, 'index.json'),
    `${JSON.stringify(
      {
        generated_at: new Date().toISOString(),
        categories,
      },
      null,
      2,
    )}\n`,
    'utf-8',
  );
};

main().catch((error) => {
  console.error('[sync:help-docs] failed', error);
  process.exitCode = 1;
});
