/** Turns "intro_to_testing.pdf" into "intro to testing" as the default
 * course title, editable before the upload starts. */
export function defaultTitleFromFilename(name: string): string {
  const withoutExtension = name.replace(/\.[^./]+$/, "");
  const spaced = withoutExtension.replace(/[_-]+/g, " ").trim();
  return spaced || "Untitled course";
}
