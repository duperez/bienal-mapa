import { defineConfig } from "vite";

export default defineConfig({
  // base relativa: o mesmo build funciona na raiz (servidor local) e em
  // subcaminho (GitHub Pages em /bienal-mapa/)
  base: "./",
});
