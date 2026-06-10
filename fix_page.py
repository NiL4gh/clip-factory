import re

with open('frontend/src/app/page.tsx', 'r', encoding='utf-8') as f:
    text = f.read()

pattern = re.compile(r'\}\s*else if \(val === "clean"\)\s*\{\s*updateGlobalSetting\("layout_mode", "box"\);\s*updateGlobalSetting\("bg_style", "white"\);\s*updateGlobalSetting\("caption_style", "Classic"\);\s*updateGlobalSetting\("title_style", "Box"\);\s*updateGlobalSetting\("hook_display", "full"\);\s*className=', re.MULTILINE | re.DOTALL)

replacement = '''} else if (val === "clean") {
                      updateGlobalSetting("layout_mode", "box");
                      updateGlobalSetting("bg_style", "white");
                      updateGlobalSetting("caption_style", "Classic");
                      updateGlobalSetting("title_style", "Box");
                      updateGlobalSetting("hook_display", "full");
                    } else if (val === "viral-italic") {
                      updateGlobalSetting("layout_mode", "box");
                      updateGlobalSetting("bg_style", "brand");
                      updateGlobalSetting("caption_style", "Pop");
                      updateGlobalSetting("title_style", "ViralItalic");
                      updateGlobalSetting("hook_display", "3s");
                    }
                  }}
                  className='''

new_text, count = pattern.subn(replacement, text)
print(f'Replaced {count} times')

with open('frontend/src/app/page.tsx', 'w', encoding='utf-8') as f:
    f.write(new_text)
