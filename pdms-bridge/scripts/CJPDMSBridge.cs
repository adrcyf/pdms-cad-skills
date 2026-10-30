// Local PDMS 12.1 adapter; original author/maintainer: adrcyf.
// CommandLine.Command is marked AVEVA USE ONLY in the installed SDK documentation.
// This compatibility adapter is version-specific; not an AVEVA supported public API.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Windows.Forms;
using System.Xml;
using Aveva.PDMS.PMLNet;
using Aveva.Pdms.Utilities.CommandLine;

[assembly: PMLNetCallable()]
namespace CJ.PDMS {
 public class StartupAddin : Aveva.ApplicationFramework.IAddin {
  private LocalBridge bridge;
  public string Name { get { return "CJ PDMS Bridge"; } }
  public string Description { get { return "Local command transport for PDMS 12.1"; } }
  public void Start(Aveva.ApplicationFramework.ServiceManager services) {
   bridge=new LocalBridge();
   bridge.Start(Path.Combine(Environment.GetEnvironmentVariable("USERPROFILE"),
               ".codex\\context\\pdms-bridge\\runtime"));
  }
  public void Stop() { if(bridge!=null) bridge.Stop(); }
 }
 [PMLNetCallable()]
 public class LocalBridge {
  private static Timer timer;
  private static string root, session;
  private static bool busy;
  private static int pid;
  [PMLNetCallable()] public LocalBridge() {}
  [PMLNetCallable()] public void Assign(LocalBridge other) {}
  [PMLNetCallable()] public string Start(string directory) {
   if(timer != null) return session;
   root=Path.GetFullPath(directory); Directory.CreateDirectory(root);
   pid=Process.GetCurrentProcess().Id;
   session=Guid.NewGuid().ToString("N");
   timer=new Timer(); timer.Interval=250; timer.Tick+=Tick; Heartbeat(false); timer.Start();
   return session;
  }
  [PMLNetCallable()] public void Stop() {
   if(timer!=null) {timer.Stop(); timer.Dispose(); timer=null; Heartbeat(true);}
  }
  private static string J(string value) {
   if(value==null) return "null";
   StringBuilder s=new StringBuilder("\"");
   foreach(char c in value) {
    if(c=='"') s.Append("\\\""); else if(c=='\\') s.Append("\\\\");
    else if(c<32) s.Append("\\u"+((int)c).ToString("x4")); else s.Append(c);
   }
   return s.Append('"').ToString();
  }
  private static void Atomic(string path,string content) {
   string temp=path+".writing"; File.WriteAllText(temp,content,new UTF8Encoding(false));
   if(File.Exists(path)) File.Delete(path); File.Move(temp,path);
  }
  private static void Heartbeat(bool stopped) {
   Atomic(Path.Combine(root,"session.json"),"{\"session\":"+J(session)+",\"pid\":"+pid+
     ",\"utc\":"+J(DateTime.UtcNow.ToString("o"))+",\"stopped\":"+(stopped?"true":"false")+
     ",\"adapter\":\"PDMS12.1-SP4-v1\"}");
  }
  private static void Tick(object sender,EventArgs e) {
   if(busy) return; busy=true;
   try {
    Heartbeat(false);
    string[] jobs=Directory.GetFiles(root,"*.request"); Array.Sort(jobs,StringComparer.Ordinal);
    if(jobs.Length>0) ProcessJob(jobs[0]);
   } catch(Exception ex) {
    try { Atomic(Path.Combine(root,"adapter-error.txt"),DateTime.UtcNow.ToString("o")+" "+ex.ToString()); } catch {}
   } finally {busy=false;}
  }
  private static void ProcessJob(string path) {
   string id=Path.GetFileNameWithoutExtension(path);
   string running=Path.Combine(root,id+".running");
   File.Move(path,running); // Claim once; never automatically retry a claimed request.
   StringBuilder results=new StringBuilder(); bool success=true; string failure=null;
   Stopwatch watch=Stopwatch.StartNew();
   try {
    XmlDocument xml=new XmlDocument(); xml.XmlResolver=null; xml.Load(running);
    XmlElement request=xml.DocumentElement;
    if(request.GetAttribute("id")!=id || request.GetAttribute("session")!=session)
      throw new InvalidOperationException("Request belongs to another session");
    double expires=Double.Parse(request.GetAttribute("expires"),CultureInfo.InvariantCulture);
    double now=(DateTime.UtcNow-new DateTime(1970,1,1)).TotalSeconds;
    if(now>expires) throw new InvalidOperationException("Request expired before execution");
    XmlNodeList lines=request.SelectNodes("command");
    if(lines.Count<1 || lines.Count>2000) throw new InvalidOperationException("Invalid batch length");
    foreach(XmlNode line in lines) {
     string text=line.InnerText;
     if(text.Trim().Length==0 || text.IndexOf('\n')>=0 || text.IndexOf('\r')>=0 || text.IndexOf('\0')>=0)
       throw new InvalidOperationException("Expected one native command per item");
    }
    foreach(XmlNode line in lines) {
     Command command=Command.CreateCommand(line.InnerText);
     bool ok=command.RunInCurrentScope();
     string error=ok?null:Convert.ToString(command.Error,CultureInfo.InvariantCulture);
     if(results.Length>0) results.Append(',');
     results.Append("{\"command\":"+J(line.InnerText)+",\"ok\":"+(ok?"true":"false")+
                    ",\"output\":"+J(command.Result)+",\"error\":"+J(error)+"}");
     if(!ok) {success=false; break;}
    }
   } catch(Exception ex) {success=false; failure=ex.ToString();}
   watch.Stop();
   Atomic(Path.Combine(root,id+".response"),"{\"request_id\":"+J(id)+",\"session\":"+J(session)+
     ",\"pid\":"+pid+",\"ok\":"+(success?"true":"false")+",\"elapsed_ms\":"+watch.ElapsedMilliseconds+
     ",\"error\":"+J(failure)+",\"results\":["+results.ToString()+"]}");
  }
 }
}
