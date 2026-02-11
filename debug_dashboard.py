
rows = "" # Dummy rows
html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Sen-Gateway Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            pre::-webkit-scrollbar {{ width: 6px; height: 6px; }} 
            pre::-webkit-scrollbar-thumb {{ background: #4b5563; border-radius: 10px; }}
            .nav-item.active {{ background-color: #374151; color: white; }}
            /* Simple toggle switch */
            .toggle-checkbox:checked {{
                right: 0;
                border-color: #2563EB;
            }}
            .toggle-checkbox:checked + .toggle-label {{
                background-color: #2563EB;
            }}
            .toggle-checkbox {{
                right: 0;
                z-index: 1;
                border-color: #D1D5DB;
                transition: all 0.3s;
                transform: translateX(-100%);
            }}
            .toggle-checkbox:checked {{
                transform: translateX(0);
                border-color: white;
            }}
        </style>
    </head>
    <body class="bg-gray-100 font-sans h-screen overflow-hidden flex">
        
        <!-- Sidebar -->
        <aside class="w-64 bg-gray-900 text-gray-400 flex flex-col shadow-xl z-10">
            <!-- (Content omitted for brevity) -->
        </aside>

        <!-- Main Content -->
        <main class="flex-1 overflow-auto relative">
            
            <!-- Monitor View -->
            <div id="section-monitor" class="p-8 max-w-7xl mx-auto">
                <!-- (Content omitted) -->
            </div>

            <!-- Config View -->
            <div id="section-config" class="hidden p-8 max-w-3xl mx-auto">
                <!-- (Content omitted) -->
            </div>

        </main>

        <script>
            const MODEL_OPTIONS = {{
                "gemini": [
                    {{"val": "gemini/gemini-3-pro-preview", "label": "顶级旗舰 (gemini/gemini-3-pro-preview)"}},
                    {{"val": "gemini/gemini-2.5-pro", "label": "高性能推理 (gemini/gemini-2.5-pro)"}},
                    {{"val": "gemini/gemini-3-flash-preview", "label": "平衡之选 (gemini/gemini-3-flash-preview)"}},
                    {{"val": "gemini/gemini-2.5-flash", "label": "高性价比 (gemini/gemini-2.5-flash)"}},
                    {{"val": "gemini/gemini-2.5-flash-lite", "label": "轻量级 (gemini/gemini-2.5-flash-lite)"}},
                    {{"val": "gemini/gemini-1.5-pro", "label": "老款稳定 (gemini/gemini-1.5-pro)"}},
                    {{"val": "custom", "label": "Other / Custom..."}}
                ],
                "openai": [
                    {{"val": "openai/gpt-5.2-pro", "label": "地表最强 (openai/gpt-5.2-pro)"}},
                    {{"val": "openai/gpt-5.2", "label": "全能选手 (openai/gpt-5.2)"}},
                    {{"val": "openai/o3-pro", "label": "推理专用 (openai/o3-pro)"}},
                    {{"val": "openai/o3-mini", "label": "高速推理 (openai/o3-mini)"}},
                    {{"val": "openai/gpt-5-mini", "label": "经济实惠 (openai/gpt-5-mini)"}},
                    {{"val": "openai/gpt-5-nano", "label": "极速版 (openai/gpt-5-nano)"}},
                    {{"val": "openai/gpt-4o", "label": "经典款 (openai/gpt-4o)"}},
                    {{"val": "custom", "label": "Other / Custom..."}}
                ],
                "anthropic": [
                    {{"val": "anthropic/claude-4-6-opus", "label": "顶级智慧 (anthropic/claude-4-6-opus)"}},
                    {{"val": "anthropic/claude-4-5-sonnet", "label": "全能主力 (anthropic/claude-4-5-sonnet)"}},
                    {{"val": "anthropic/claude-4-5-haiku", "label": "高性价比 (anthropic/claude-4-5-haiku)"}},
                    {{"val": "anthropic/claude-3-7-sonnet", "label": "平衡版本 (anthropic/claude-3-7-sonnet)"}},
                    {{"val": "anthropic/claude-5-sonnet-preview", "label": "特殊分支 (anthropic/claude-5-sonnet-preview)"}},
                    {{"val": "custom", "label": "Other / Custom..."}}
                ]
            }}; 

            // Navigation Logic
            function showSection(sectionId) {{
                document.getElementById('section-monitor').classList.add('hidden');
            }}
        </script>
    </body>
    </html>
    """

print(html_content)
