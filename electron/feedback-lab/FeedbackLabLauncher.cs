using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class FeedbackLabLauncher
{
    [STAThread]
    private static void Main()
    {
        const string project = @"I:\工作\项目\模组agent\electron";
        string electron = Path.Combine(project, "node_modules", "electron", "dist", "electron.exe");
        string entry = Path.Combine(project, "feedback-lab", "main.js");
        if (!File.Exists(electron) || !File.Exists(entry))
        {
            MessageBox.Show("找不到 Feedback Lab 运行文件，请确认项目目录仍位于：\n" + project,
                "ModAgent Feedback Lab", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        Process.Start(new ProcessStartInfo
        {
            FileName = electron,
            Arguments = "\"" + entry + "\"",
            WorkingDirectory = project,
            UseShellExecute = false,
            CreateNoWindow = true
        });
    }
}
