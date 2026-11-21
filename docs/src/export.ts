import html2canvas from "html2canvas";
import { chartTheme } from "./theme";

/**
 * 把 src 複製到畫面外撐寬、截圖並下載成 PNG；原本畫面上的元素完全不受影響（不會閃一下）。
 * fit 在 html2canvas 的 iframe（桌面版 CSS）裡執行，用來把 clone 撐到表格完整寬度。
 */
export function exportPng(src: HTMLElement, filename: string, fit: (el: HTMLElement) => void) {
  // 複製一份到畫面外撐寬、截圖，原本畫面上的元素完全不受影響（不會閃一下）
  const clone = src.cloneNode(true) as HTMLElement;
  clone.classList.add("exporting");
  clone.style.position = "fixed";
  clone.style.top = "-99999px";
  clone.style.left = "0";
  clone.style.overflow = "visible";
  document.body.appendChild(clone);

  html2canvas(clone, {
    scale: 4,
    backgroundColor: chartTheme().bg,
    // html2canvas 會在這個寬度的 iframe 裡重排版，固定 1280 讓手機也套用桌面版 CSS
    windowWidth: 1280,
    // clone 是 position:fixed，與捲動位置無關；固定 scroll 為 0，避免 iOS
    // 在 iframe 內 scrollTo 失敗造成截圖範圍位移
    scrollX: 0,
    scrollY: 0,
    // 寬度要在 iframe（桌面版 CSS）裡量，不能在原頁面量：手機原頁面套的是
    // 手機版 CSS，量出的尺寸與實際截圖時的排版不同，會截不完整。
    // 不傳 width/height，html2canvas 會在 onclone 之後依 clone 的實際範圍截圖
    onclone: (_doc, el) => fit(el),
  })
    .then((canvas) => {
      document.body.removeChild(clone);
      const a = document.createElement("a");
      a.download = filename;
      a.href = canvas.toDataURL("image/png");
      a.click();
    })
    .catch((err) => {
      document.body.removeChild(clone);
      console.error(err);
    });
}
