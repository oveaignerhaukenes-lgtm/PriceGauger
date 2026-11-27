"""Native Lightweight Charts payloads for research; no trading authority."""
from datetime import timedelta
from math import isfinite

def line_data(rows,value):
    """Sorted second timestamps; whitespace marks missing values/feed holes."""
    data={}
    prev=None
    for row in rows:
        t=int(row["at"].timestamp())
        if prev is not None and t-prev>4:
            data[prev+1]={"time":prev+1}
        v=value(row)
        data[t]={"time":t,"value":float(v)} if isinstance(v,(int,float)) and isfinite(v) else {"time":t}
        prev=t
    return list(data.values())

def series(rows,role,label,color,value,*,pane="price",width=1,dashed=False,last=False):
    return dict(role=role,label=label,color=color,line_width=width,dashed=dashed,
                last_value_visible=last,pane=pane,data=line_data(rows,value))

def payload(rows,*,key,title,value,lines=(),markers=(),panes=("price",),height=350,share=.43,variant=""):
    return dict(chart_id=key,signature="research-native:"+variant+":"+":".join(panes)+":"+":".join(x["role"] for x in lines),
                market=title,timeframe="1s BBO",seconds_visible=True,vertical_touch_drag=True,
                height=height,price_panel_share=share,pane_order=list(panes),
                primary_line=line_data(rows,value),lines=list(lines),markers=list(markers))

def ic14_payload(rows,*,key,side,arms=False,original=False,research=False,details=False):
    lines=[]
    def add(role,label,color,f,**kw):
        lines.append(series(rows,role,label,color,f,**kw))
    add("hold","HOLD","#16a34a" if side=="LONG" else "#f59e0b",lambda r:r["mid"] if r.get("target")==side else None,width=3)
    for role,label,color,dash in (("entry_price","ENTRY-grense","#38bdf8",False),
                                  ("normal_price","Normal EXIT","#ef4444",False),
                                  ("urgent_price","Akutt EXIT","#a81e38",True)):
        add(role,label,color,lambda r,k=role:r.get(k),dashed=dash,width=2)
    if original:
        add("entry_base_price","Entry uten Gain","#9ca3af",lambda r:r.get("entry_base_price"),dashed=True)
    if arms:
        for role,label in (("entry_fast_price","Rask arm"),("entry_slow_price","Treg arm")):
            add(role,label,"#7dd3fc",lambda r,k=role:r.get(k),dashed=True)
    marks=[]
    for r in rows:
        d=r.get("decision")
        if d:
            entry=d=="QUALIFIED_IMPULSE_V14"
            marks.append(dict(time=int(r["at"].timestamp()),position="atPriceMiddle",price=r["mid"],
                              shape=("arrowUp" if side=="LONG" else "arrowDown") if entry else "square",
                              color="#38bdf8" if entry else "#ef4444",size=1.1,text=("ENTRY" if entry else "EXIT") if details else ""))
        elif r.get("entry_rejected") or r.get("gate")=="ENTRY_CONFIRM":
            marks.append(dict(time=int(r["at"].timestamp()),position="atPriceMiddle",price=r["mid"],
                              shape="circle",color="#eab308",size=.35,text=""))
    return payload(rows,key=key,title="IC v1.4 · "+side+(" · RESEARCH" if research else ""),
                   value=lambda r:r["mid"],lines=lines,markers=marks,variant=side)

def indicator_payload(rows,*,key,indicator,label,threshold=0.):
    lines=() if indicator=="atr" else tuple(series(rows,"threshold"+str(i),"Terskel","#eab308",lambda r,v=v:v,dashed=True)
                  for i,v in enumerate(sorted({threshold,-threshold})))
    return payload(rows,key=key,title=label,value=lambda r:r.get(indicator),
                   lines=lines,height=235,variant=indicator)

def diagnostics_payload(rows,*,key):
    lines=[series(rows,"entry_ref","Entry-krav","#ef4444",lambda r:1.,dashed=True)]
    for role,label,color in (("retrace","Retrace","#38bdf8"),("exit_threshold","Normal terskel","#ef4444"),("urgent","Akutt terskel","#a81e38")):
        lines.append(series(rows,role,label,color,lambda r,k=role:r.get(k),pane="exit"))
    return payload(rows,key=key,title="Impuls / krav · retrace",value=lambda r:r.get("entry_ratio"),lines=lines,panes=("price","exit"),height=360,share=.5)

def dsp_payload(rows,*,key,stages,labels):
    lines=[series(rows,"raw","Rå bevegelse","#94a3b8",lambda r:r.get("raw"),pane="velocity"),
           series(rows,"processed","Prosessert","#38bdf8",lambda r:r.get("processed"),pane="velocity",width=2)]
    palette=("#eab308","#c084fc","#38bdf8","#fb923c","#f9a8d4","#a5b4fc","#94a3b8","#fde68a")
    for i,stage in enumerate(stages):
        lines.append(series(rows,"gain:"+str(i),f"{i+1} · {labels[stage.kind]}",palette[i],
                      lambda r,j=i:r["gains"][j] if len(r["gains"])>j else None,pane="gain"))
    panes=("price","velocity","gain") if stages else ("price","velocity")
    return payload(rows,key=key,title="Signal Lab · rå pris / bevegelse / gain",
                   value=lambda r:None if r.get("gap") else r["mid"],lines=lines,panes=panes,height=420,share=.43,
                   variant=":".join(stage.kind for stage in stages))
