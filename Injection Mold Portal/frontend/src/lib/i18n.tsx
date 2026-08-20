import { createContext, useContext, useState, type ReactNode } from "react";
import { en } from "./locales/en";
import { th } from "./locales/th";

export type Lang = "en" | "th";

const DICTS: Record<Lang, Widen<typeof en>> = { en, th };
const LANG_KEY = "imp_lang";

type DotPaths<T, Prefix extends string = ""> = {
  [K in keyof T & string]: T[K] extends string
    ? `${Prefix}${K}`
    : DotPaths<T[K], `${Prefix}${K}.`>;
}[keyof T & string];

export type TKey = DotPaths<typeof en>;

export type Widen<T> = { [K in keyof T]: T[K] extends string ? string : Widen<T[K]> };

function lookup(dict: unknown, path: string): string | undefined {
  const parts = path.split(".");
  let node: unknown = dict;
  for (const part of parts) {
    if (typeof node !== "object" || node === null) return undefined;
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === "string" ? node : undefined;
}

interface I18nState {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: TKey, vars?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nState | null>(null);

function interpolate(text: string, vars?: Record<string, string | number>): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (match, key) => (key in vars ? String(vars[key]) : match));
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    const stored = localStorage.getItem(LANG_KEY);
    return stored === "th" || stored === "en" ? stored : "en";
  });

  function setLang(next: Lang) {
    localStorage.setItem(LANG_KEY, next);
    setLangState(next);
  }

  function t(key: TKey, vars?: Record<string, string | number>): string {
    const value = lookup(DICTS[lang], key) ?? lookup(DICTS.en, key) ?? key;
    return interpolate(value, vars);
  }

  return <I18nContext.Provider value={{ lang, setLang, t }}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nState {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}
