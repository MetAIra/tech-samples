# unity-webgl-ime-bridge

Unity WebGL の IMGUI(`GUILayout.TextField` など)で日本語入力(IME)を使えるようにする、最小のブリッジです。
入力欄がフォーカスされている間だけ、同じ位置に HTML の `<input>` / `<textarea>` を重ねてブラウザに入力させ、値を毎フレーム Unity 側へ読み戻します。

## できること

- WebGL ビルドの IMGUI 入力欄で、日本語の変換と確定ができる
- 1 行の欄・パスワード欄(伏せ字)・複数行の欄に対応
- Enter(複数行は Ctrl+Enter)で「送信された」ことを C# 側から取れる
- 入力中は移動キーなどを Unity に流さない(入力欄にキーが食われない)
- エディタやデスクトップでは通常の IMGUI として動く(呼び出し側のコードは共通)

## 仕組み

1. C# の `WebGlTextInput.Field("Id", value, maxLen)` は、内部で通常の `GUILayout.TextField` を描いたうえで、そのコントロールがフォーカスされたかを `GUI.GetNameOfFocusedControl()` で見ます。
2. フォーカスされたら、`GUILayoutUtility.GetLastRect()` で得た矩形を画面座標に直し、`.jslib` の `TiShow` で同じ位置に HTML の入力欄を出します。同時に `WebGLInput.captureAllKeyboardInput` を切って、キーボードをブラウザ側に渡します。
3. 表示中は毎フレーム `TiGetValue` で HTML 側の値を読み戻し、`TiMove` で位置を追従させます。
4. Enter が押されると `.jslib` 側がフラグを立て、C# は `Submitted("Id")` で受け取ります。IME の変換確定の Enter(`isComposing` / `keyCode 229`)は送信として扱いません。
5. Esc・欄の外をクリック(blur)・IMGUI 側のフォーカス喪失のいずれかで HTML 欄を閉じ、キーボードの取り扱いを Unity に戻します。

矩形は Repaint イベントのときにだけ正しく取れるため、表示と移動は Repaint 時にだけ行います。

## 組み込み手順

1. `Assets/Plugins/WebGL/TextInput.jslib` と `Assets/Scripts/WebGlTextInput.cs` をプロジェクトにコピーします(`.jslib` は `Assets/Plugins/WebGL/` 配下に置くこと)。
2. `GUILayout.TextField(v, n)` を `WebGlTextInput.Field("任意のId", v, n)` に置き換えます。パスワードは `Password`、複数行は `Area`。
3. Enter で送る欄では、`WebGlTextInput.Submitted("Id")` が true になったときに送信処理を呼びます(HTML 側の Enter は Unity の `KeyCode.Return` としては届きません)。
4. 送信後に欄を空にするときは、C# 側の変数と `WebGlTextInput.SetValue("Id", "")` の両方を更新します。
5. 画面を切り替えて欄が描かれなくなる前に `WebGlTextInput.CloseAll()` を呼びます(閉じ忘れると HTML 欄だけが残ります)。
6. キー操作(移動など)を持つコードでは、`WebGlTextInput.AnyActive` が true の間はキー処理を止めます。

`Assets/Scripts/Sample/ImeBridgeSample.cs` を空のシーンの GameObject に付けると、上の使い方をそのまま試せます。

## 注意点

- IME の変換確定の Enter を送信と誤認しないよう、`keydown` で `isComposing` と `keyCode === 229` を素通しにしています。ここを外すと、変換のたびに送信されます。
- canvas を全画面(`SetFullscreen`)にしている間は、`body` 直下の HTML 要素が隠れるため入力欄は出ません。全画面を解除してから入力してください。
- パスワード欄は `type=password` ではなく `type=text` + CSS の伏せ字にしています。`type=password` だとブラウザのパスワードマネージャが保存済みの別の資格情報を自動入力し、意図しない組み合わせで送信されることがあるためです。
- HTML 欄の見た目(枠線・背景・フォント)は `.jslib` の `cssText` で決めています。プロジェクトの見た目に合わせて調整してください。
- 動作確認: Unity 2022.3 LTS の WebGL ビルド、デスクトップの Chrome。他の環境は未確認です。

## ファイル

| ファイル | 役割 |
|---|---|
| `Assets/Plugins/WebGL/TextInput.jslib` | HTML 入力欄の生成・配置・値の受け渡し(ブラウザ側) |
| `Assets/Scripts/WebGlTextInput.cs` | IMGUI の置き換え API と、フォーカスに応じた表示・同期(Unity 側) |
| `Assets/Scripts/Sample/ImeBridgeSample.cs` | 使い方の最小サンプル |
