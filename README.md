# Task Mode

Code for **Task Mode: Dynamic Filtering for Task-Specific Web Navigation using LLMs** (ASSETS 2025).
Ananya Gubbi Mohanbabu, Yotam Sechayk, Amy Pavel.

[Paper](https://arxiv.org/abs/2507.14769) · [Project page](https://ananyagm.com/task-mode/task-mode.html)

Task Mode is a Chrome extension that filters a webpage down to the content relevant to the user's task.
It scores every element on the page for task relevance and can show the page with color gradients, with
less relevant content faded, or with only task-specific content kept (for both sighted and screen reader users).

## Contents

- `manifest.json`, `background.js`, `content.js`, `interface.html/.js/.css`: the Chrome extension
- `text.py`: Flask server that scores text elements (GPT-4o and Sentence-BERT), port 5000
- `clip.py`: Flask server that scores images and icons (CLIP and GPT-4o), port 5001

## Setup

1. Install the Python dependencies:

   ```
   pip install -r requirements.txt
   ```

2. Set your OpenAI API key and start both servers (each in its own terminal):

   ```
   export OPENAI_API_KEY=your-key
   python3 text.py
   python3 clip.py
   ```

3. In Chrome, open `chrome://extensions`, turn on Developer mode, click **Load unpacked**, and select this folder.

4. Open a webpage, click the Task Mode extension icon, and enter your task.
