//+------------------------------------------------------------------+
//|  TbotOverlay.mq5                                                  |
//|  Draws tbot's own state on the chart: open positions, their stop  |
//|  and target, and each symbol's strategy phase.                    |
//|                                                                   |
//|  Pairs with the SMC/ICT visualizer: that one shows what MT5       |
//|  detected, this one shows what the bot did about it.              |
//|                                                                   |
//|  Reads <Common>\Files\<InpFolder>\tbot_state.json, written by     |
//|  tbot.interfaces.overlay. Read-only: it places no orders and      |
//|  changes nothing. Timestamps in that file are already broker time.|
//+------------------------------------------------------------------+
#property copyright "tbot"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

input string InpFolder      = "SMC_Export";  // Common\Files subfolder (matches tbot config)
input string InpFile        = "tbot_state.json";
input int    InpRefreshSecs = 2;             // how often to re-read the file
input color  InpLongColor   = clrDodgerBlue;
input color  InpShortColor  = clrOrangeRed;
input color  InpStopColor   = clrCrimson;
input color  InpTargetColor = clrMediumSeaGreen;
input bool   InpShowPanel   = true;          // status text in the corner

const string PREFIX = "tbot_";
string   g_path;
datetime g_last_read = 0;

//+------------------------------------------------------------------+
//| Minimal JSON helpers.                                            |
//|                                                                  |
//| Deliberately not a full parser. The file is written by one known |
//| producer with a fixed shape, so scanning for keys is enough and  |
//| keeps this indicator dependency-free and easy to audit.          |
//+------------------------------------------------------------------+
string JsonStr(const string src, const string key, const int from = 0)
  {
   string needle = "\"" + key + "\"";
   int k = StringFind(src, needle, from);
   if(k < 0) return "";
   int colon = StringFind(src, ":", k);
   if(colon < 0) return "";
   int q1 = StringFind(src, "\"", colon);
   if(q1 < 0) return "";
   int q2 = StringFind(src, "\"", q1 + 1);
   if(q2 < 0) return "";
   return StringSubstr(src, q1 + 1, q2 - q1 - 1);
  }

double JsonNum(const string src, const string key, const int from = 0)
  {
   string needle = "\"" + key + "\"";
   int k = StringFind(src, needle, from);
   if(k < 0) return 0.0;
   int colon = StringFind(src, ":", k);
   if(colon < 0) return 0.0;
   int i = colon + 1;
   while(i < StringLen(src) && StringGetCharacter(src, i) == ' ') i++;
   int start = i;
   while(i < StringLen(src))
     {
      ushort c = StringGetCharacter(src, i);
      if((c >= '0' && c <= '9') || c == '-' || c == '+' || c == '.' || c == 'e' || c == 'E') i++;
      else break;
     }
   if(i == start) return 0.0;
   return StringToDouble(StringSubstr(src, start, i - start));
  }

//+------------------------------------------------------------------+
//| Object helpers                                                   |
//+------------------------------------------------------------------+
void DrawLine(const string name, const double price, const color clr,
              const ENUM_LINE_STYLE style, const string text)
  {
   string id = PREFIX + name;
   if(ObjectFind(0, id) < 0)
      ObjectCreate(0, id, OBJ_HLINE, 0, 0, price);
   ObjectSetDouble(0, id, OBJPROP_PRICE, price);
   ObjectSetInteger(0, id, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, id, OBJPROP_STYLE, style);
   ObjectSetInteger(0, id, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, id, OBJPROP_BACK, true);
   ObjectSetInteger(0, id, OBJPROP_SELECTABLE, false);
   ObjectSetString(0, id, OBJPROP_TOOLTIP, text);
  }

void DrawLabel(const string name, const int corner_y, const string text, const color clr)
  {
   string id = PREFIX + name;
   if(ObjectFind(0, id) < 0)
      ObjectCreate(0, id, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, id, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, id, OBJPROP_XDISTANCE, 12);
   ObjectSetInteger(0, id, OBJPROP_YDISTANCE, corner_y);
   ObjectSetInteger(0, id, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, id, OBJPROP_FONTSIZE, 9);
   ObjectSetInteger(0, id, OBJPROP_SELECTABLE, false);
   ObjectSetString(0, id, OBJPROP_TEXT, text);
  }

void ClearObjects()
  {
   ObjectsDeleteAll(0, PREFIX);
  }

//+------------------------------------------------------------------+
//| Read and draw                                                    |
//+------------------------------------------------------------------+
bool ReadFile(string &out)
  {
   int h = FileOpen(g_path, FILE_READ | FILE_BIN | FILE_COMMON);
   if(h == INVALID_HANDLE) return false;
   ulong size = FileSize(h);
   if(size == 0 || size > 4 * 1024 * 1024) { FileClose(h); return false; }
   uchar bytes[];
   ArrayResize(bytes, (int)size);
   FileReadArray(h, bytes, 0, (int)size);
   FileClose(h);
   out = CharArrayToString(bytes, 0, (int)size, CP_UTF8);
   return StringLen(out) > 0;
  }

void Refresh()
  {
   string json;
   if(!ReadFile(json))
     {
      ClearObjects();
      if(InpShowPanel)
         DrawLabel("panel0", 20, "tbot: no state file (" + g_path + ")", clrGray);
      return;
     }

   ClearObjects();

   string mode   = JsonStr(json, "mode");
   string as_of  = JsonStr(json, "as_of");
   double equity = JsonNum(json, "equity");
   double day    = JsonNum(json, "day_pnl");
   bool   paused = StringFind(json, "\"paused\": true") >= 0;

   if(InpShowPanel)
     {
      DrawLabel("panel0", 20,
                StringFormat("tbot %s%s  equity %.2f  today %+.2f",
                             mode, paused ? " (PAUSED)" : "", equity, day),
                paused ? clrGoldenrod : clrSilver);
      DrawLabel("panel1", 36, "as of " + as_of + " (broker time)", clrGray);
     }

   // Walk the positions array, drawing only this chart's symbol.
   int cursor = StringFind(json, "\"positions\"");
   if(cursor < 0) return;
   int drawn = 0;
   while(true)
     {
      int item = StringFind(json, "\"symbol\"", cursor);
      if(item < 0) break;
      string sym = JsonStr(json, "symbol", item);
      // "phases" also contains symbol keys; stop once past the positions array.
      int phases_at = StringFind(json, "\"phases\"");
      if(phases_at >= 0 && item > phases_at) break;

      if(sym == _Symbol)
        {
         string side = JsonStr(json, "side", item);
         double entry = JsonNum(json, "entry", item);
         double sl    = JsonNum(json, "sl", item);
         double tp    = JsonNum(json, "tp", item);
         double vol   = JsonNum(json, "volume", item);
         double pnl   = JsonNum(json, "pnl", item);
         color  clr   = (side == "LONG") ? InpLongColor : InpShortColor;
         string tag   = StringFormat("%d", drawn);

         DrawLine("entry" + tag, entry, clr, STYLE_SOLID,
                  StringFormat("tbot %s %.2f lots, open P/L %.2f", side, vol, pnl));
         if(sl > 0) DrawLine("sl" + tag, sl, InpStopColor, STYLE_DASH, "tbot stop");
         if(tp > 0) DrawLine("tp" + tag, tp, InpTargetColor, STYLE_DASH, "tbot target");
         drawn++;
        }
      cursor = item + 8;
     }

   if(InpShowPanel)
     {
      string phase = "";
      int p = StringFind(json, "\"" + _Symbol + "\"", StringFind(json, "\"phases\""));
      if(p >= 0) phase = JsonStr(json, "phase", p);
      DrawLabel("panel2", 52,
                StringFormat("%s: %s  |  %d position(s) drawn",
                             _Symbol, phase == "" ? "-" : phase, drawn),
                clrSilver);
     }
   ChartRedraw(0);
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   g_path = InpFolder + "\\" + InpFile;
   EventSetTimer(MathMax(1, InpRefreshSecs));
   Refresh();
   return INIT_SUCCEEDED;
  }

void OnTimer() { Refresh(); }

int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[])
  {
   return rates_total;  // drawing is timer-driven; nothing to compute per tick
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   ClearObjects();
   ChartRedraw(0);
  }
//+------------------------------------------------------------------+
