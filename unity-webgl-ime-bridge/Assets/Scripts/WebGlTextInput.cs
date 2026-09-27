using System.Collections.Generic;
using System.Runtime.InteropServices;
using UnityEngine;

/// <summary>
/// IMGUI の文字入力欄を WebGL でも日本語入力できるようにする薄いラッパー。
///
/// 背景: Unity WebGL の IMGUI(GUILayout.TextField 等)は IME(日本語変換)が効かない。
/// 対策: 入力欄がフォーカスされている間だけ、同じ位置に HTML の input/textarea を重ねて
///       ブラウザに入力させる(Assets/Plugins/WebGL/TextInput.jslib)。値は毎フレーム読み戻す。
///       重ねている間は WebGLInput.captureAllKeyboardInput を切り、キーを Unity に食わせない。
/// 使い方: GUILayout.TextField(v, n) の代わりに WebGlTextInput.Field("Id", v, n)。
///       Enter で送る欄は Submitted("Id") を見る(HTML 側の Enter は Unity に届かないため)。
///       デスクトップ/エディタでは従来の IMGUI をそのまま呼ぶだけ(挙動は変わらない)。
/// 注意: GUILayoutUtility.GetLastRect() は Repaint イベントのときしか正しい矩形を返さない。
///       そのため表示・移動は Repaint 時にだけ行う。
/// </summary>
public static class WebGlTextInput
{
#if UNITY_WEBGL && !UNITY_EDITOR
    private const bool Supported = true;
    [DllImport("__Internal")] private static extern void TiShow(string id, float x, float y, float w, float h, string text, int mode, int maxLen);
    [DllImport("__Internal")] private static extern void TiMove(string id, float x, float y, float w, float h);
    [DllImport("__Internal")] private static extern void TiHide(string id);
    [DllImport("__Internal")] private static extern int TiState(string id);
    [DllImport("__Internal")] private static extern string TiGetValue(string id);
    [DllImport("__Internal")] private static extern void TiSetValue(string id, string text);
#else
    private const bool Supported = false;
    private static void TiShow(string id, float x, float y, float w, float h, string text, int mode, int maxLen) { }
    private static void TiMove(string id, float x, float y, float w, float h) { }
    private static void TiHide(string id) { }
    private static int TiState(string id) => 0;
    private static string TiGetValue(string id) => "";
    private static void TiSetValue(string id, string text) { }
#endif

    private static readonly HashSet<string> _shown = new HashSet<string>();
    private static readonly HashSet<string> _submitted = new HashSet<string>();
    private static readonly Dictionary<string, Rect> _rects = new Dictionary<string, Rect>();

    /// <summary>HTML の入力欄を重ねている最中か(移動やショートカットを止めるゲートに使う)</summary>
    public static bool AnyActive => _shown.Count > 0;

    /// <summary>GUILayout.TextField の置き換え</summary>
    public static string Field(string id, string value, int maxLen, params GUILayoutOption[] opts)
    {
        GUI.SetNextControlName(id);
        var v = GUILayout.TextField(value ?? "", maxLen, opts);
        return Sync(id, v, GUILayoutUtility.GetLastRect(), maxLen, 0);
    }

    /// <summary>GUILayout.PasswordField の置き換え</summary>
    public static string Password(string id, string value, int maxLen, params GUILayoutOption[] opts)
    {
        GUI.SetNextControlName(id);
        var v = GUILayout.PasswordField(value ?? "", '*', maxLen, opts);
        return Sync(id, v, GUILayoutUtility.GetLastRect(), maxLen, 1);
    }

    /// <summary>GUI.TextField(Rect, ...) の置き換え</summary>
    public static string Field(string id, Rect rect, string value, int maxLen)
    {
        GUI.SetNextControlName(id);
        var v = GUI.TextField(rect, value ?? "", maxLen);
        return Sync(id, v, rect, maxLen, 0);
    }

    /// <summary>GUILayout.TextArea の置き換え(複数行。HTML 側は textarea・Ctrl+Enter で submitted)</summary>
    public static string Area(string id, string value, int maxLen, params GUILayoutOption[] opts)
    {
        GUI.SetNextControlName(id);
        var v = GUILayout.TextArea(value ?? "", maxLen, opts);
        return Sync(id, v, GUILayoutUtility.GetLastRect(), maxLen, 2);
    }

    /// <summary>HTML 側で Enter が押されたか(一度読むとクリア)。デスクトップでは常に false</summary>
    public static bool Submitted(string id) => _submitted.Remove(id);

    /// <summary>C# 側で値を書き換えたとき(送信後の空欄化など)に HTML 側へも反映する</summary>
    public static void SetValue(string id, string value)
    {
        if (Supported && _shown.Contains(id)) TiSetValue(id, value ?? "");
    }

    /// <summary>重ねている HTML 欄をすべて閉じる(画面を切り替えて欄が描かれなくなる前に呼ぶ)</summary>
    public static void CloseAll()
    {
        foreach (var id in new List<string>(_shown)) Close(id);
    }

    /// <summary>HTML の入力欄を閉じる(IMGUI のフォーカスは呼び出し側で外す)</summary>
    public static void Close(string id)
    {
        if (!_shown.Remove(id)) return;
        TiHide(id);
        if (_shown.Count == 0) SetCapture(true);
    }

    private static string Sync(string id, string value, Rect guiRect, int maxLen, int mode)
    {
        if (!Supported) return value;
        var e = Event.current;
        bool repaint = e != null && e.type == EventType.Repaint;
        bool focused = GUI.GetNameOfFocusedControl() == id;

        if (repaint)
        {
            // GUI 座標(BeginArea/ScrollView の中)→ 画面座標(canvas のピクセル)
            var min = GUIUtility.GUIToScreenPoint(new Vector2(guiRect.xMin, guiRect.yMin));
            var max = GUIUtility.GUIToScreenPoint(new Vector2(guiRect.xMax, guiRect.yMax));
            _rects[id] = Rect.MinMaxRect(min.x, min.y, max.x, max.y);
        }

        if (_shown.Contains(id))
        {
            int st = TiState(id);
            if ((st & 2) != 0) _submitted.Add(id);
            var cur = TiGetValue(id) ?? "";
            bool browserClosed = (st & 1) == 0;
            if (browserClosed || !focused)
            {
                Close(id);
                // ブラウザ側で閉じた(blur/Esc)なら IMGUI のフォーカスも外す = 移動キーが入力欄に食われない
                if (browserClosed && focused) GUI.FocusControl(null);
                return cur;
            }
            if (repaint && _rects.TryGetValue(id, out var rr))
                TiMove(id, rr.x, rr.y, rr.width, rr.height);
            return cur;
        }

        if (focused && repaint && _rects.TryGetValue(id, out var r) && r.width > 0f && r.height > 0f)
        {
            _shown.Add(id);
            SetCapture(false);
            TiShow(id, r.x, r.y, r.width, r.height, value ?? "", mode, maxLen);
        }
        return value;
    }

    private static void SetCapture(bool on)
    {
#if UNITY_WEBGL && !UNITY_EDITOR
        WebGLInput.captureAllKeyboardInput = on;
#endif
    }
}
