from server.tools.production_tools import append_log

def notify(role: str, message: str, level: str="info"):
    append_log({"actor":"tool","action":"notify","target":role,"message": message, "level": level})
    return {"status":"ok","msg":"notification logged"}
