// A tiny DOM for running birds/web/static/widgets.js under Node (no jsdom): elements, text nodes, attributes,
// classList, style.setProperty, events, focus, querySelectorAll by [attr] / .class, getElementById.
// Enough for the widget tests in tests/test_widgets.py; not a browser.
class Node_ {
  constructor(type) {
    this.nodeType = type;
    this.parentNode = null;
    this.childNodes = [];
  }
  get children() {
    return this.childNodes.filter((c) => c.nodeType === 1);
  }
  get textContent() {
    return this.nodeType === 3 ? this.data : this.childNodes.map((c) => c.textContent).join("");
  }
  set textContent(v) {
    if (this.nodeType === 3) this.data = String(v);
    else {
      this.childNodes = [];
      if (v !== "") this.append(new Text_(String(v)));
    }
  }
  append(...nodes) {
    for (const n of nodes) {
      const node = n && n.nodeType ? n : new Text_(String(n));
      node.remove?.();
      node.parentNode = this;
      this.childNodes.push(node);
    }
  }
  replaceChildren(...nodes) {
    for (const c of this.childNodes) c.parentNode = null;
    this.childNodes = [];
    this.append(...nodes);
  }
  remove() {
    if (this.parentNode) {
      const p = this.parentNode;
      p.childNodes = p.childNodes.filter((c) => c !== this);
      this.parentNode = null;
      if (globalThis.document.activeElement && !globalThis.document.contains(globalThis.document.activeElement))
        globalThis.document.activeElement = globalThis.document.body;
    }
  }
}
class Text_ extends Node_ {
  constructor(data) {
    super(3);
    this.data = data;
  }
}
class Element_ extends Node_ {
  constructor(tag) {
    super(1);
    this.tagName = tag.toUpperCase();
    this.attributes = {};
    this.listeners = {};
    this.style = { props: {}, setProperty: (k, v) => (this.style.props[k] = v) };
    const el = this;
    this.classList = {
      add: (...c) => (el.className = [...new Set([...el._cls(), ...c])].join(" ")),
      remove: (...c) => (el.className = el._cls().filter((x) => !c.includes(x)).join(" ")),
      toggle: (c, on) => ((on ?? !el._cls().includes(c)) ? el.classList.add(c) : el.classList.remove(c)),
      contains: (c) => el._cls().includes(c),
    };
    this.className = "";
    this.hidden = false;
    this.disabled = false;
  }
  _cls() {
    return String(this.className || "").split(/\s+/).filter(Boolean);
  }
  setAttribute(k, v) {
    this.attributes[k] = String(v);
    if (k === "id") this.id = String(v);
    if (k === "value") this.value = String(v);
  }
  getAttribute(k) {
    return k in this.attributes ? this.attributes[k] : null;
  }
  removeAttribute(k) {
    delete this.attributes[k];
  }
  get dataset() {
    const out = {};
    for (const [k, v] of Object.entries(this.attributes))
      if (k.startsWith("data-")) out[k.slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = v;
    return out;
  }
  set innerHTML(html) {
    this.childNodes = [];
    const m = /^<(\w+)/.exec(html);
    if (m) this.append(new Element_(m[1]));
  }
  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }
  dispatch(type, extra = {}) {
    const ev = { type, target: this, currentTarget: this, preventDefault() {}, ...extra };
    for (const fn of this.listeners[type] || []) fn(ev);
  }
  click() {
    this.dispatch("click");
  }
  focus() {
    globalThis.document.activeElement = this;
  }
  scrollIntoView() {}
  _all() {
    return this.children.flatMap((c) => [c, ...c._all()]);
  }
  _match(sel) {
    const a = /^\[([\w-]+)\]$/.exec(sel);
    if (a) return this.getAttribute(a[1]) !== null;
    const c = /^\.([\w-]+)$/.exec(sel);
    if (c) return this._cls().includes(c[1]);
    return this.tagName === sel.toUpperCase();
  }
  querySelectorAll(sel) {
    return this._all().filter((e) => e._match(sel));
  }
  querySelector(sel) {
    return this.querySelectorAll(sel)[0] || null;
  }
  contains(node) {
    for (let n = node; n; n = n.parentNode) if (n === this) return true;
    return false;
  }
}

export function install() {
  const body = new Element_("body");
  const root = new Element_("html");
  root.append(body);
  const document = {
    body,
    documentElement: root,
    activeElement: body,
    createElement: (t) => new Element_(t),
    createTextNode: (d) => new Text_(d),
    getElementById: (id) => root._all().find((e) => e.id === id) || null,
    contains: (n) => root.contains(n),
    addEventListener() {},
  };
  globalThis.document = document;
  globalThis.window = { setTimeout: (fn) => 0, addEventListener() {} };
  globalThis.matchMedia = () => ({ matches: false });
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
  globalThis.Image = class {
    set src(v) {
      this._src = v;
    }
  };
  return document;
}
