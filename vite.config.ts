import { cpSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vite";

const root = resolve(import.meta.dirname, "docs");
const outDir = resolve(import.meta.dirname, "dist");

export default defineConfig({
  root,
  // GitHub Pages 部署在 /<repo>/ 子路徑下，用相對路徑才不用寫死 repo 名稱
  base: "./",
  build: {
    outDir,
    emptyOutDir: true,
    rolldownOptions: {
      input: {
        index: resolve(root, "index.html"),
        dca: resolve(root, "dca.html"),
        bear: resolve(root, "bear.html"),
      },
      output: {
        codeSplitting: {
          groups: [{ name: "echarts", test: /node_modules[\\/](echarts|zrender)[\\/]/ }],
        },
      },
    },
    // ECharts 完整版約 1 MB（與原本 vendored 的 echarts.min.js 同大小），不是意外變大
    chunkSizeWarningLimit: 1100,
  },
  plugins: [
    {
      // data/*.json 是執行期才 fetch() 的，Vite 不會自動打包；開發時 dev server 直接讀 docs/data/
      name: "copy-data",
      apply: "build",
      closeBundle() {
        cpSync(resolve(root, "data"), resolve(outDir, "data"), { recursive: true });
      },
    },
  ],
});
