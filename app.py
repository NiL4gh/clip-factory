import gradio as gr
from shorts_generator.pipeline import OpusPipeline
# Import your catalogs and helpers here...

pipeline = OpusPipeline(work_dir="/content/drive/MyDrive/shorts_generator/work")

def analyze_ui(url, llm_idx, wsp_idx):
    # Logic to call pipeline.process_new_video
    # Return clips for the UI table
    pass

with gr.Blocks() as demo:
    gr.Markdown("# 🚀 Opus-Clone Pro")
    url_input = gr.Textbox(label="YouTube URL")
    analyze_btn = gr.Button("Find Viral Clips")
    results = gr.Dataframe(headers=["Title", "Score", "Reason"])
    
    analyze_btn.click(analyze_ui, inputs=[url_input], outputs=[results])

if __name__ == "__main__":
    demo.launch(share=True)
