import {
  Code20Regular,
  Document20Regular,
  DocumentError20Regular,
  DocumentLock20Regular,
  DocumentPdf20Regular,
  DocumentText20Regular,
  Folder20Regular,
  Image20Regular,
  Mail20Regular,
  SlideText20Regular,
  Table20Regular,
} from '@fluentui/react-icons';

const BY_TYPE = {
  pdf: DocumentPdf20Regular,
  txt: DocumentText20Regular,
  markdown: DocumentText20Regular,
  rtf: DocumentText20Regular,
  doc: Document20Regular,
  docx: Document20Regular,
  csv: Table20Regular,
  tsv: Table20Regular,
  parquet: Table20Regular,
  xls: Table20Regular,
  xlsx: Table20Regular,
  ppt: SlideText20Regular,
  pptx: SlideText20Regular,
  png: Image20Regular,
  jpg: Image20Regular,
  tiff: Image20Regular,
  eml: Mail20Regular,
  json: Code20Regular,
  ndjson: Code20Regular,
  yaml: Code20Regular,
  xml: Code20Regular,
  html: Code20Regular,
  mhtml: Code20Regular,
  css: Code20Regular,
  js: Code20Regular,
};

/**
 * The icon of a source: a folder, or a file.
 * @param {{ type: 'file' | 'folder' }} props
 */
export function SourceIcon({ type }) {
  return type === 'folder' ? (
    <Folder20Regular aria-label="Folder" />
  ) : (
    <Document20Regular aria-label="File" />
  );
}

/**
 * The icon of a file of a source. A kind of file nothing reads shows a document with an error; a
 * known kind that is "unsupported" needs a password and shows a lock; other kinds show their own.
 * @param {{ file: import('../api/client.js').FileRow }} props
 */
export function FileIcon({ file }) {
  if (file.protected) return <DocumentLock20Regular aria-label="Password protected" />;
  if (!file.file_type) return <DocumentError20Regular aria-label="Unsupported format" />;
  const Icon = BY_TYPE[file.file_type] ?? Document20Regular;
  return <Icon aria-label={file.file_type} />;
}
