let cachedConfig = null;

export async function loadPaperConfig() {
  if (cachedConfig) return cachedConfig;
  const url = new URL("../../configs/paper.json", import.meta.url);
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Unable to load paper configuration (${response.status})`);
  cachedConfig = await response.json();
  return cachedConfig;
}
