/* 取頁面上一定存在的元素；找不到代表 HTML 與程式不同步，直接丟錯比靜默失敗好查 */
export function byId<T extends HTMLElement = HTMLElement>(id: string): T {
  const el = document.getElementById(id);
  if (!el) throw new Error(`找不到元素 #${id}`);
  return el as T;
}

export function query<T extends Element = HTMLElement>(
  selector: string,
  parent: ParentNode = document,
): T {
  const el = parent.querySelector<T>(selector);
  if (!el) throw new Error(`找不到元素 ${selector}`);
  return el;
}
