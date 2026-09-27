using UnityEngine;

/// <summary>
/// WebGlTextInput の使い方を示す最小のサンプル。空のシーンの任意の GameObject に付けるだけで動く。
/// 1 行の入力欄・パスワード欄・複数行の欄と、Enter で送信されたテキストの表示を含む。
/// WebGL ビルドでは各欄にフォーカスすると HTML の入力欄が重なり、日本語入力ができる。
/// エディタやデスクトップでは通常の IMGUI として動く。
/// </summary>
public class ImeBridgeSample : MonoBehaviour
{
    private string _name = "";
    private string _password = "";
    private string _memo = "";
    private string _lastSubmitted = "";

    private void Update()
    {
        // HTML の入力欄を重ねている間は、移動などのキー操作を止める(キーを入力欄に食わせないため)
        if (WebGlTextInput.AnyActive) return;

        // ここに通常のキー操作(WASD 移動など)を書く
    }

    private void OnGUI()
    {
        GUILayout.BeginArea(new Rect(20, 20, 420, 300), GUI.skin.box);
        GUILayout.Label("名前(Enter で送信)");
        _name = WebGlTextInput.Field("Name", _name, 30);
        if (WebGlTextInput.Submitted("Name")) Submit(_name);

        GUILayout.Label("パスワード(伏せ字)");
        _password = WebGlTextInput.Password("Password", _password, 64);

        GUILayout.Label("メモ(複数行・Ctrl+Enter で送信)");
        _memo = WebGlTextInput.Area("Memo", _memo, 500, GUILayout.Height(80));
        if (WebGlTextInput.Submitted("Memo")) Submit(_memo);

        // デスクトップ向け: ボタンでも送れるようにしておく
        if (GUILayout.Button("送信")) Submit(_name);

        GUILayout.Space(8);
        GUILayout.Label("最後に送信された内容: " + _lastSubmitted);
        GUILayout.EndArea();
    }

    private void Submit(string text)
    {
        _lastSubmitted = text;
        // 送信後に欄を空にするときは、C# 側の値と HTML 側の値の両方を更新する
        _name = "";
        WebGlTextInput.SetValue("Name", "");
        GUI.FocusControl(null);
    }
}
