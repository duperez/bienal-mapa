// Monta um percurso pela interface de verdade e fotografa a tela.
//
//   node foto.mjs <porta> <saida.png> "Alvo 1" "Alvo 2" ...
//
// Existe porque nem todo defeito de mapa é testável por asserção. "O caminho
// não segue a rua" foi relatado com um print, e a rota que o produzia passava
// em todas as verificações: nunca atravessava parede, chegava ao destino, e o
// comprimento batia. Só o olho pegava. Depois de achar a causa dá para escrever
// o teste (test-rota.mjs mede a folga média até a parede) — mas primeiro é
// preciso enxergar.
import { chromium } from "playwright";
const [porta, saida, ...alvos] = process.argv.slice(2);
const nav = await chromium.launch();
const pg = await nav.newPage({ viewport: { width: 1500, height: 950 } });
await pg.goto(`http://localhost:${porta}/`, { waitUntil: "networkidle" });
await pg.waitForTimeout(2500);
for (const termo of alvos) {
  await pg.fill("#searchInput", termo);
  await pg.waitForTimeout(500);
  await pg.click("#searchResults > *:first-child");
  await pg.waitForTimeout(400);
  await pg.click("#sheetRota");
  await pg.waitForTimeout(600);
}
await pg.waitForTimeout(2500);
await pg.screenshot({ path: saida });
console.log("ok", saida);
await nav.close();
