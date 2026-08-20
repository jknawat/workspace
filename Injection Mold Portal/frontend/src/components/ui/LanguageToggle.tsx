import { useI18n } from "../../lib/i18n";

export function LanguageToggle() {
  const { lang, setLang } = useI18n();

  return (
    <button
      onClick={() => setLang(lang === "en" ? "th" : "en")}
      aria-label="Switch language"
      className="relative inline-flex h-8 w-16 shrink-0 items-center rounded-full border border-border-strong bg-surface-raised text-[10px] font-bold"
    >
      <span
        className={`absolute top-0.5 h-6 w-7 rounded-full bg-brand-blue transition-transform ${
          lang === "th" ? "translate-x-[34px]" : "translate-x-0.5"
        }`}
      />
      <span className={`z-10 flex-1 text-center ${lang === "en" ? "text-white" : "text-ink-muted"}`}>
        EN
      </span>
      <span className={`z-10 flex-1 text-center ${lang === "th" ? "text-white" : "text-ink-muted"}`}>
        TH
      </span>
    </button>
  );
}
