export type ThemePreference = "system" | "light" | "dark";
export type EffectiveTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "smv2.theme";

function createThemeBootstrapScript(storageKey: string): string {
  return `(function(){try{var s=localStorage.getItem(${JSON.stringify(storageKey)});var p=(s==="light"||s==="dark"||s==="system")?s:"system";var e=p==="system"?(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"):p;document.documentElement.setAttribute("data-theme",e);}catch(err){}})();`;
}

export const THEME_BOOTSTRAP_SCRIPT = createThemeBootstrapScript(THEME_STORAGE_KEY);
