/**
 * A small RFC-4180 parser for browser-side CSV reading.
 *
 * The import drop zone reads `.csv` files in the browser so the mapping table can
 * be shown before a byte leaves the machine. This parser exists because the
 * obvious shortcut — `text.split(delimiter)` — corrupts data silently, which is
 * the worst failure mode an import can have: a quoted field may contain the
 * delimiter, a doubled `""` is one literal quote, and a quoted field may span two
 * lines. Each of those misaligns every column after the broken field, and a wrong
 * header maps the whole file onto the wrong gradebook fields.
 *
 * Two dialects are accepted, `,` and `;`, because German and French spreadsheets
 * routinely separate with the semicolon; the delimiter is sniffed from the first
 * line. A UTF-8 BOM, which Excel writes, is stripped so it does not become part of
 * the first header.
 */

export interface ParsedCsv {
  /** The first row, used for the column mapping table. */
  headers: string[];
  /** The data rows, the header excluded. */
  rows: string[][];
}

/**
 * Parse CSV text into a header row and data rows.
 *
 * @param text - The decoded file contents, possibly with a UTF-8 BOM.
 * @returns The header row and the data rows.
 */
export function parseCsv(text: string): ParsedCsv {
  const source = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  const delimiter = sniffDelimiter(source);

  const all: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;

  const endField = () => {
    row.push(field);
    field = "";
  };
  const endRow = () => {
    endField();
    all.push(row);
    row = [];
  };

  for (let i = 0; i < source.length; i++) {
    const char = source[i];
    if (quoted) {
      if (char === '"') {
        // A doubled quote is one literal quote; a single one closes the field.
        if (source[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          quoted = false;
        }
      } else {
        // Newlines and delimiters inside a quoted field are ordinary characters.
        field += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === delimiter) {
      endField();
    } else if (char === "\r") {
      if (source[i + 1] === "\n") i++;
      endRow();
    } else if (char === "\n") {
      endRow();
    } else {
      field += char;
    }
  }

  // A final newline already ended the last row; only a trailing row without one
  // reaches here, and it is not dropped.
  if (field !== "" || row.length > 0) endRow();

  if (all.length === 0) return { headers: [], rows: [] };
  const [headers, ...rows] = all;
  return { headers, rows };
}

/**
 * Pick the delimiter from the first line.
 *
 * Delimiters inside quotes are ignored, so a header like `"a,b";c` is not taken
 * for a comma-separated file. A tie falls back to the comma, the RFC-4180
 * default.
 */
function sniffDelimiter(text: string): "," | ";" {
  let commas = 0;
  let semicolons = 0;
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === "\n" || char === "\r") break;
    if (quoted) {
      if (char === '"') quoted = false;
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      commas++;
    } else if (char === ";") {
      semicolons++;
    }
  }
  return semicolons > commas ? ";" : ",";
}
