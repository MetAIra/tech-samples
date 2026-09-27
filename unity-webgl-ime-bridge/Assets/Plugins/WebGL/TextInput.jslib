// Unity WebGL 用 文字入力ブリッジ(JavaScript 側)
//
// IMGUI(GUILayout.TextField 等)は Unity WebGL で IME(日本語変換)が効かない。
// そこで入力欄がフォーカスされている間だけ、同じ位置に HTML の <input>/<textarea> を重ねて
// ブラウザ側に入力させる。C# 側は WebGlTextInput.cs(値は C# が毎フレーム TiGetValue で読み戻す)。
//   mode: 0=1行テキスト / 1=パスワード / 2=複数行(textarea)
//   Enter(textarea は Ctrl+Enter)で submitted、Esc/blur で閉じる(値は保持)
//   注意1: IME 変換確定の Enter は isComposing=true / keyCode=229 で来るので送信扱いにしない
//   注意2: canvas の全画面(SetFullscreen)中は body 直下の要素が隠れるため HTML 欄は出ない
//          = 全画面を解除して入力する
mergeInto(LibraryManager.library, {
  TiShow: function (idPtr, x, y, w, h, textPtr, mode, maxLen) {
    var id = UTF8ToString(idPtr), text = UTF8ToString(textPtr);
    if (!window._ti) window._ti = {};
    if (!window._tiPlace) {
      // GUI 座標(canvas のピクセル)→ ページ上の位置。CSS で拡縮された canvas にも追従する
      window._tiPlace = function (el, x, y, w, h) {
        var canvas = (typeof Module !== 'undefined' && Module.canvas) ||
                     document.querySelector('#unity-canvas') || document.querySelector('canvas');
        if (!canvas) return;
        var r = canvas.getBoundingClientRect();
        var sx = canvas.width ? r.width / canvas.width : 1;
        var sy = canvas.height ? r.height / canvas.height : 1;
        el.style.left = (r.left + x * sx) + 'px';
        el.style.top = (r.top + y * sy) + 'px';
        el.style.width = Math.max(40, w * sx) + 'px';
        el.style.height = Math.max(18, h * sy) + 'px';
        el.style.fontSize = Math.max(11, Math.min(18, h * sy * 0.6)) + 'px';
      };
    }
    var st = window._ti[id];
    if (!st) {
      var el = document.createElement(mode === 2 ? 'textarea' : 'input');
      // パスワード欄も type=text にして CSS で伏せ字にする。type=password だとブラウザのパスワード
      // マネージャが保存済みの別の資格情報を自動入力し、意図しない組み合わせで送信されることがある
      if (mode !== 2) el.type = 'text';
      if (mode === 1) { el.style.webkitTextSecurity = 'disc'; el.setAttribute('data-ti-password', '1'); }
      el.setAttribute('autocomplete', 'off');
      el.setAttribute('name', 'ti-' + id + '-' + Math.floor(Math.random() * 1e9));
      el.setAttribute('autocapitalize', 'off');
      el.setAttribute('spellcheck', 'false');
      el.style.cssText = 'position:fixed;z-index:10000;box-sizing:border-box;margin:0;padding:2px 4px;' +
        'border:1px solid #6cf;border-radius:3px;background:#fff;color:#111;font-family:sans-serif;' +
        'outline:none;resize:none;line-height:1.3;display:none;';
      st = { el: el, visible: false, submitted: false, mode: mode };
      window._ti[id] = st;
      el.addEventListener('keydown', function (ev) {
        // IME の変換確定の Enter(isComposing / keyCode 229)は送信ではない。変換中のキーは素通しする
        if (ev.isComposing || ev.keyCode === 229) { ev.stopPropagation(); return; }
        if (ev.key === 'Enter' && (st.mode !== 2 || ev.ctrlKey)) { ev.preventDefault(); st.submitted = true; }
        else if (ev.key === 'Escape') { ev.preventDefault(); el.blur(); }
        ev.stopPropagation(); // Unity 側のキーボード処理(移動キーなど)に流さない
      });
      el.addEventListener('keyup', function (ev) { ev.stopPropagation(); });
      el.addEventListener('keypress', function (ev) { ev.stopPropagation(); });
      el.addEventListener('blur', function () { st.visible = false; el.style.display = 'none'; });
      document.body.appendChild(el);
    }
    if (maxLen > 0) st.el.maxLength = maxLen;
    st.el.value = text;
    st.submitted = false;
    st.visible = true;
    st.el.style.display = 'block';
    window._tiPlace(st.el, x, y, w, h);
    st.el.focus();
    try { var n = st.el.value.length; st.el.setSelectionRange(n, n); } catch (e) {}
  },

  TiMove: function (idPtr, x, y, w, h) {
    var id = UTF8ToString(idPtr);
    var st = window._ti && window._ti[id];
    if (st && st.visible && window._tiPlace) window._tiPlace(st.el, x, y, w, h);
  },

  TiHide: function (idPtr) {
    var id = UTF8ToString(idPtr);
    var st = window._ti && window._ti[id];
    if (!st) return;
    st.visible = false;
    st.el.style.display = 'none';
    try { st.el.blur(); } catch (e) {}
  },

  // bit0: 表示中 / bit1: Enter で送信された(読むとクリア)
  TiState: function (idPtr) {
    var id = UTF8ToString(idPtr);
    var st = window._ti && window._ti[id];
    if (!st) return 0;
    var v = (st.visible ? 1 : 0) | (st.submitted ? 2 : 0);
    st.submitted = false;
    return v;
  },

  TiGetValue: function (idPtr) {
    var id = UTF8ToString(idPtr);
    var st = window._ti && window._ti[id];
    var s = st ? (st.el.value || '') : '';
    var size = lengthBytesUTF8(s) + 1;
    var buf = _malloc(size);
    stringToUTF8(s, buf, size);
    return buf;
  },

  TiSetValue: function (idPtr, textPtr) {
    var id = UTF8ToString(idPtr), text = UTF8ToString(textPtr);
    var st = window._ti && window._ti[id];
    if (st) st.el.value = text;
  }
});
