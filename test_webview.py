import webview

html = "<h1 style='color:white;background:#0a0a0a;padding:20px'>Hello WebView</h1>"
window = webview.create_window("Test", html=html, width=400, height=300)
webview.start()