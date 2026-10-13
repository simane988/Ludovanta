// Managed by Ludovanta - do not edit, it is overwritten by 'python3 .ludovanta/ludovanta.py update'.
//
// Screenshots for AI agents, requested by 'ludovanta.py screenshot' through a JSON request file:
//   HEADLESS: Unity runs in batchmode with -executeMethod Ludovanta.Editor.Capture.Batch -ludovantaRequest <file>.
//   LIVE:     the open Editor polls Temp/ludovanta/capture/ for *.request.json files.
// The answer is <id>.result.json next to the request. Entering Play mode reloads the domain, so a request that waits
// for Play mode is kept in SessionState. Only long-standing Unity APIs are used here: a compile error in this package
// would stop the whole project from compiling.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Ludovanta.Editor
{
    [Serializable]
    public class CaptureRequest
    {
        public string id = "";
        public string scene = "";
        public string camera = "";
        public string output = "";      // absolute path of the PNG; with several frames -01, -02 ... are added
        public int width = 1280;
        public int height = 720;
        public float play;              // seconds of Play mode before the first frame; 0: no Play mode
        public int frames = 1;          // frames are taken in Play mode only
        public float every = 0.25f;     // seconds between frames

        // State while the request waits for Play mode, kept across the domain reload.
        public string resultPath = "";
        public bool batch;
        public bool series;             // several frames in Play mode: files get -01, -02 ...
        public bool enteredPlay;
        public double deadline;
        public double nextFrameAt;
        public int taken;
        public bool uniform;
        public string cameraUsed = "";
    }

    [Serializable]
    public class CaptureResult
    {
        public string id = "";
        public bool ok;
        public string error = "";
        public List<string> files = new List<string>();
        public string scene = "";
        public string camera = "";
        public bool playMode;
        public bool uniform;
        public int width;
        public int height;
    }

    [InitializeOnLoad]
    public static class Capture
    {
        const string LiveFolder = "Temp/ludovanta/capture";
        const string PendingKey = "Ludovanta.Capture.Pending";
        const double PlayStartSeconds = 180;
        static readonly Type CanvasType = Type.GetType("UnityEngine.Canvas, UnityEngine.UIModule");
        static double nextPoll;

        static Capture()
        {
            EditorApplication.update += Update;
        }

        // Batchmode entry point: -executeMethod Ludovanta.Editor.Capture.Batch -ludovantaRequest <file>
        public static void Batch()
        {
            string requestPath = Argument("-ludovantaRequest");
            if (string.IsNullOrEmpty(requestPath))
            {
                Debug.LogError("Ludovanta: -ludovantaRequest <file> is missing");
                EditorApplication.Exit(2);
                return;
            }
            Start(requestPath, true);
        }

        static string Argument(string name)
        {
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == name) return args[i + 1];
            }
            return null;
        }

        static void Update()
        {
            string pending = SessionState.GetString(PendingKey, "");
            if (pending.Length > 0)
            {
                Continue(JsonUtility.FromJson<CaptureRequest>(pending));
                return;
            }
            if (Application.isBatchMode || EditorApplication.timeSinceStartup < nextPoll) return;
            nextPoll = EditorApplication.timeSinceStartup + 0.5;
            if (!Directory.Exists(LiveFolder)) return;
            foreach (string file in Directory.GetFiles(LiveFolder, "*.request.json"))
            {
                string taken = file + ".taken";
                try
                {
                    File.Move(file, taken);
                }
                catch (IOException)
                {
                    continue;
                }
                Start(taken, false);
                return;
            }
        }

        static void Start(string requestPath, bool batch)
        {
            CaptureRequest req = null;
            try
            {
                req = JsonUtility.FromJson<CaptureRequest>(File.ReadAllText(requestPath));
                req.batch = batch;
                req.resultPath = Path.Combine(Path.GetDirectoryName(requestPath), req.id + ".result.json");
                if (batch)
                {
                    OpenScene(req);
                }
                else if (!string.IsNullOrEmpty(req.scene) && !SceneOpen(req.scene))
                {
                    throw new Exception("scene " + req.scene + " is not open in the Editor. Ludovanta does not switch " +
                                        "scenes in an open Editor (unsaved work): open it there, or leave out --scene");
                }
                if (string.IsNullOrEmpty(req.scene)) req.scene = SceneManager.GetActiveScene().path;
                req.series = req.frames > 1 && (req.play > 0 || EditorApplication.isPlaying);

                if (req.play > 0 && !EditorApplication.isPlaying)
                {
                    req.enteredPlay = true;
                    req.deadline = EditorApplication.timeSinceStartup + PlayStartSeconds;
                    Save(req);
                    EditorApplication.EnterPlaymode();
                    return;
                }
                if (EditorApplication.isPlaying)
                {
                    req.nextFrameAt = EditorApplication.timeSinceStartup + req.play;
                    Save(req);
                    return;
                }
                Shoot(req);
                Finish(req, null);
            }
            catch (Exception e)
            {
                if (req == null)
                {
                    Debug.LogError("Ludovanta: cannot read the screenshot request " + requestPath + ": " + e.Message);
                    if (batch) EditorApplication.Exit(1);
                    return;
                }
                Finish(req, e.Message);
            }
        }

        static void Continue(CaptureRequest req)
        {
            try
            {
                double now = EditorApplication.timeSinceStartup;
                if (!EditorApplication.isPlaying)
                {
                    if (req.taken > 0) throw new Exception("Play mode ended before all frames were captured");
                    if (now > req.deadline) throw new Exception("Play mode did not start (compile errors? see the log)");
                    return;
                }
                if (req.nextFrameAt <= 0)
                {
                    req.nextFrameAt = now + req.play;
                    Save(req);
                    return;
                }
                if (now < req.nextFrameAt) return;
                Shoot(req);
                if (req.series && req.taken < req.frames)
                {
                    req.nextFrameAt = now + Math.Max(0.02f, req.every);
                    Save(req);
                    return;
                }
                Finish(req, null);
            }
            catch (Exception e)
            {
                Finish(req, e.Message);
            }
        }

        static void Save(CaptureRequest req)
        {
            SessionState.SetString(PendingKey, JsonUtility.ToJson(req));
        }

        static void Finish(CaptureRequest req, string error)
        {
            SessionState.EraseString(PendingKey);
            var result = new CaptureResult
            {
                id = req.id, ok = error == null, error = error ?? "", scene = req.scene, camera = req.cameraUsed,
                playMode = EditorApplication.isPlaying, uniform = req.uniform, width = req.width, height = req.height
            };
            for (int i = 0; i < req.taken; i++) result.files.Add(FramePath(req, i));
            try
            {
                File.WriteAllText(req.resultPath, JsonUtility.ToJson(result, true));
            }
            catch (Exception e)
            {
                Debug.LogError("Ludovanta: cannot write " + req.resultPath + ": " + e.Message);
            }
            if (req.batch)
            {
                EditorApplication.Exit(error == null ? 0 : 1);
            }
            else if (req.enteredPlay && EditorApplication.isPlaying)
            {
                EditorApplication.ExitPlaymode();
            }
        }

        static string FramePath(CaptureRequest req, int index)
        {
            if (!req.series) return req.output;
            string folder = Path.GetDirectoryName(req.output);
            string name = Path.GetFileNameWithoutExtension(req.output);
            return Path.Combine(folder, name + "-" + (index + 1).ToString("00") + ".png");
        }

        static void OpenScene(CaptureRequest req)
        {
            string scene = req.scene;
            if (string.IsNullOrEmpty(scene))
            {
                foreach (EditorBuildSettingsScene s in EditorBuildSettings.scenes)
                {
                    if (s.enabled)
                    {
                        scene = s.path;
                        break;
                    }
                }
                if (string.IsNullOrEmpty(scene))
                {
                    throw new Exception("no --scene given and no enabled scene in File > Build Settings");
                }
            }
            if (!File.Exists(scene)) throw new Exception("scene not found: " + scene);
            EditorSceneManager.OpenScene(scene, OpenSceneMode.Single);
            req.scene = scene;
        }

        static bool SceneOpen(string path)
        {
            for (int i = 0; i < SceneManager.sceneCount; i++)
            {
                if (SceneManager.GetSceneAt(i).path == path) return true;
            }
            return false;
        }

        // --- Rendering ------------------------------------------------------------------------------

        static void Shoot(CaptureRequest req)
        {
            Camera cam = FindCamera(req.camera);
            Texture2D tex = Render(cam, req.width, req.height);
            try
            {
                string path = FramePath(req, req.taken);
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                File.WriteAllBytes(path, tex.EncodeToPNG());
                if (Uniform(tex)) req.uniform = true;
                req.cameraUsed = cam.name;
                req.taken++;
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(tex);
            }
        }

        static List<Camera> SceneCameras()
        {
            var cameras = new List<Camera>();
            foreach (Camera c in Resources.FindObjectsOfTypeAll<Camera>())
            {
                if (c.isActiveAndEnabled && c.gameObject.scene.IsValid() && (c.hideFlags & HideFlags.HideInHierarchy) == 0)
                {
                    cameras.Add(c);
                }
            }
            return cameras;
        }

        static Camera FindCamera(string name)
        {
            List<Camera> cameras = SceneCameras();
            if (!string.IsNullOrEmpty(name))
            {
                foreach (Camera c in cameras)
                {
                    if (c.name == name) return c;
                }
                var names = new List<string>();
                foreach (Camera c in cameras) names.Add(c.name);
                throw new Exception("camera '" + name + "' not found among the enabled cameras: " +
                                    (names.Count > 0 ? string.Join(", ", names.ToArray()) : "none"));
            }
            if (Camera.main != null && Camera.main.isActiveAndEnabled) return Camera.main;
            if (cameras.Count > 0) return cameras[0];
            throw new Exception("no enabled camera in the open scene" +
                                (EditorApplication.isPlaying ? "" : "; if the game creates its camera at runtime, use --play"));
        }

        static Texture2D Render(Camera cam, int width, int height)
        {
            var rt = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32);
            RenderTexture previousTarget = cam.targetTexture;
            RenderTexture previousActive = RenderTexture.active;
            List<object[]> canvases = OverlayCanvasesToCamera(cam);
            try
            {
                cam.targetTexture = rt;
                cam.Render();
                RenderTexture.active = rt;
                var tex = new Texture2D(width, height, TextureFormat.RGB24, false);
                tex.ReadPixels(new Rect(0, 0, width, height), 0, 0);
                tex.Apply();
                return tex;
            }
            finally
            {
                cam.targetTexture = previousTarget;
                RenderTexture.active = previousActive;
                RestoreCanvases(canvases);
                rt.Release();
                UnityEngine.Object.DestroyImmediate(rt);
            }
        }

        static bool Uniform(Texture2D tex)
        {
            Color32[] px = tex.GetPixels32();
            for (int i = 97; i < px.Length; i += 97)
            {
                if (px[i].r != px[0].r || px[i].g != px[0].g || px[i].b != px[0].b) return false;
            }
            return true;
        }

        // Screen Space - Overlay canvases (the HUD) are drawn on the screen, not by a camera. For the shot they are
        // pointed at the camera and restored afterwards. Reflection keeps this file compiling when the UI module is off.
        static List<object[]> OverlayCanvasesToCamera(Camera cam)
        {
            var changed = new List<object[]>();
            if (CanvasType == null) return changed;
            try
            {
                PropertyInfo renderMode = CanvasType.GetProperty("renderMode");
                PropertyInfo worldCamera = CanvasType.GetProperty("worldCamera");
                PropertyInfo planeDistance = CanvasType.GetProperty("planeDistance");
                PropertyInfo isRoot = CanvasType.GetProperty("isRootCanvas");
                object overlay = Enum.ToObject(renderMode.PropertyType, 0);       // RenderMode.ScreenSpaceOverlay
                object screenCamera = Enum.ToObject(renderMode.PropertyType, 1);  // RenderMode.ScreenSpaceCamera
                foreach (UnityEngine.Object o in Resources.FindObjectsOfTypeAll(CanvasType))
                {
                    var canvas = o as Behaviour;
                    if (canvas == null || !canvas.isActiveAndEnabled || !canvas.gameObject.scene.IsValid()) continue;
                    if (!(bool)isRoot.GetValue(canvas, null) || !renderMode.GetValue(canvas, null).Equals(overlay)) continue;
                    changed.Add(new object[] { canvas, worldCamera.GetValue(canvas, null), planeDistance.GetValue(canvas, null) });
                    renderMode.SetValue(canvas, screenCamera, null);
                    worldCamera.SetValue(canvas, cam, null);
                    planeDistance.SetValue(canvas, Mathf.Max(cam.nearClipPlane * 2f, 0.1f), null);
                }
                MethodInfo force = CanvasType.GetMethod("ForceUpdateCanvases", BindingFlags.Public | BindingFlags.Static);
                if (force != null) force.Invoke(null, null);
            }
            catch (Exception e)
            {
                Debug.LogWarning("Ludovanta: the overlay UI may be missing from the screenshot: " + e.Message);
            }
            return changed;
        }

        static void RestoreCanvases(List<object[]> changed)
        {
            if (changed.Count == 0) return;
            try
            {
                PropertyInfo renderMode = CanvasType.GetProperty("renderMode");
                PropertyInfo worldCamera = CanvasType.GetProperty("worldCamera");
                PropertyInfo planeDistance = CanvasType.GetProperty("planeDistance");
                object overlay = Enum.ToObject(renderMode.PropertyType, 0);
                foreach (object[] c in changed)
                {
                    if ((UnityEngine.Object)c[0] == null) continue;
                    renderMode.SetValue(c[0], overlay, null);
                    worldCamera.SetValue(c[0], c[1], null);
                    planeDistance.SetValue(c[0], c[2], null);
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("Ludovanta: could not restore a canvas after the screenshot: " + e.Message);
            }
        }
    }
}
