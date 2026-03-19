const CJK_CHAR = "\\u3400-\\u4DBF\\u4E00-\\u9FFF";
const ASCII_WORD = "A-Za-z0-9";

const CJK_TO_ASCII_RE = new RegExp(`([${CJK_CHAR}])([${ASCII_WORD}])`, "g");
const ASCII_TO_CJK_RE = new RegExp(`([${ASCII_WORD}])([${CJK_CHAR}])`, "g");
const SPACE_RE = /\s+/g;

export function normalizeMixedScriptSpacing(value: string): string {
  return value
    .replace(SPACE_RE, " ")
    .replace(CJK_TO_ASCII_RE, "$1 $2")
    .replace(ASCII_TO_CJK_RE, "$1 $2")
    .trim();
}
