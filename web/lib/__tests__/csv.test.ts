/**
 * The CSV parser is the front gate of the import. `split` on the delimiter would
 * silently corrupt quoted fields, escaped quotes and multi-line fields — the
 * tests below pin each of those cases, because a wrong header maps every column
 * of a file to the wrong gradebook field.
 */

import { describe, expect, it } from "vitest";
import { parseCsv } from "../csv";

describe("parseCsv", () => {
  it("returns headers and data rows", () => {
    const parsed = parseCsv("first_name,last_name\nAda,Lovelace\nGrace,Hopper\n");
    expect(parsed.headers).toEqual(["first_name", "last_name"]);
    expect(parsed.rows).toEqual([
      ["Ada", "Lovelace"],
      ["Grace", "Hopper"],
    ]);
  });

  it("keeps a delimiter inside a quoted field", () => {
    const parsed = parseCsv('name,score\n"Doe, Jane",88\n');
    expect(parsed.rows[0]).toEqual(["Doe, Jane", "88"]);
  });

  it("turns a doubled quote inside a quoted field into one literal quote", () => {
    const parsed = parseCsv('note,score\n"He said ""hello""",5\n');
    expect(parsed.rows[0][0]).toBe('He said "hello"');
  });

  it("keeps a newline inside a quoted field as part of the value", () => {
    const parsed = parseCsv('notes,score\n"line one\nline two",88\n');
    expect(parsed.rows[0]).toEqual(["line one\nline two", "88"]);
  });

  it("sniffs the semicolon dialect", () => {
    const parsed = parseCsv("Vorname;Nachname\nAda;Lovelace\n");
    expect(parsed.headers).toEqual(["Vorname", "Nachname"]);
    expect(parsed.rows[0]).toEqual(["Ada", "Lovelace"]);
  });

  it("prefers the delimiter that appears more often on the header line", () => {
    // One comma (inside quotes) and two semicolons: the file is semicolon-separated.
    const parsed = parseCsv('"a,b";c;d\n"1,2";3;4\n');
    expect(parsed.headers).toEqual(["a,b", "c", "d"]);
  });

  it("defaults to the comma when the header line is tied or empty", () => {
    expect(parseCsv("a;b,c\n1;2,3\n").headers).toEqual(["a;b", "c"]);
    expect(parseCsv("a,b\n1,2\n").headers).toEqual(["a", "b"]);
  });

  it("strips a UTF-8 BOM so it does not join the first header", () => {
    const parsed = parseCsv("\uFEFFa,b\n1,2\n");
    expect(parsed.headers).toEqual(["a", "b"]);
  });

  it("accepts CRLF line endings", () => {
    const parsed = parseCsv("a,b\r\n1,2\r\n");
    expect(parsed.headers).toEqual(["a", "b"]);
    expect(parsed.rows).toEqual([["1", "2"]]);
  });

  it("does not invent a trailing row for a final newline", () => {
    expect(parseCsv("a,b\n1,2\n").rows).toHaveLength(1);
    expect(parseCsv("a,b\n1,2").rows).toHaveLength(1);
  });

  it("preserves empty fields", () => {
    const parsed = parseCsv("a,b,c\n,,\n");
    expect(parsed.rows[0]).toEqual(["", "", ""]);
  });

  it("returns empty headers for an empty file", () => {
    expect(parseCsv("")).toEqual({ headers: [], rows: [] });
  });
});
