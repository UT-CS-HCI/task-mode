import concurrent.futures
import time
import requests
from flask_cors import CORS
from PIL import Image
from transformers import CLIPProcessor, CLIPModel
from flask import Flask, request, jsonify
import torch
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
import math
import json
import openai
import os

app = Flask(__name__)
CORS(app)

DEVICE = "cpu"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
image_alt_texts = []
image_rel_scores = []
max_retries = 3
batch_size = 25
max_workers = 4 

api_key = os.environ["OPENAI_API_KEY"]


model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(DEVICE)
processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

@app.route("/process_visuals", methods=["POST"])
def process_visuals():
    data = request.get_json()
    task = data.get("task", "")
    images = data.get("images", [])
    iframes = data.get("iframes", [])
    svg = data.get("svg", [])

    
    if not task or not images:
        return jsonify({"error": "Missing task or images or svg"}), 400

    print("Received data:", task, len(images), len(iframes), len(svg))

    alt_texts = [img.get("alt", "").strip() for img in images if img.get("alt")]
    print("🖼️ Image alt texts:", alt_texts)

    img_scores = []
    svg_scores = []

    # processing iframes
    '''
    for visual in iframes:
        visual = get_clip_scores(task, visual)
        visual = get_sbert_scores(task, visual)
        visual = get_visual_scores(visual)
        scores.append(visual)
    '''
    # prcessing images
    img_scores = score_images(task, images)

    # processing svg
    svg = get_svgs(svg)
    svg_scores = score_svgs(task, svg)
    
    return jsonify({"img_scores": img_scores,"svg_scores": svg_scores})

def print_token_usage(response):
    usage = response.usage
    input_tokens = usage.prompt_tokens
    output_tokens = usage.completion_tokens
    input_cost = input_tokens * 0.005 / 1000
    output_cost = output_tokens * 0.015 / 1000
    total_cost = input_cost + output_cost

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": total_cost
    }



def task_breakdown(task):
    client = openai.OpenAI(api_key=api_key)
    prompt = f"""
    Given the user's task: "{task}", break it down into the following components to help identify and prioritize relevant page elements:

    1. entity: the main object or item the user is interested in
    2. constraints: broad category of requirements or preferences (e.g., cost, color, brand) 
    3. actions: logical steps the user might take on a webpage (e.g., filter, compare, add to cart)
    4. default: default elements the user expects to see on a webpage (e.g., product name, price, image)
    5. fallback: alternative elements the user can use if the primary ones are missing (e.g., search bar, contact support)

    Return in the following JSON format:
    {{
        "entity": "...",
        "constraints": ["...", "..."],
        "actions": ["...", "..."],
        "default": ["...", "..."],
        "fallback": ["...", "..."]
    }}
    """

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert task evaluator."},
            {"role": "user", "content": prompt}
        ]
    )
    breakdown = response.choices[0].message.content.strip()
    return breakdown

def get_clip_scores(text_features, visual):
    visual_url = visual.get("src", "")

    try:

        response = requests.get(visual_url, timeout=5)
        response.raise_for_status()  

        with Image.open(BytesIO(response.content)) as image:
            if image.mode == "P":  
                image = image.convert("RGBA")  # convert to RGBA to handle transparency
            else:
                image = image.convert("RGB")  # convert to RGB for consistency

        image_inputs = processor(images=image, return_tensors="pt").to(DEVICE)

        with torch.no_grad():
            image_features = model.get_image_features(**image_inputs)
            image_features /= image_features.norm(dim=-1, keepdim=True)

        score = (image_features @ text_features.T).squeeze().item()

        visual["clip_score"] = score
        visual["url"] = visual_url

    except Exception as _:
        visual["clip_score"] = 0  

    return visual

# def get_sbert_scores(task_embedding, visual):
    alt_text = visual.get("alt", "") or visual.get("title", "") or "No description available"

    try:
        
        text_embedding = sbert_model.encode(alt_text, convert_to_tensor=True)
        sbert_score = util.pytorch_cos_sim(task_embedding, text_embedding).squeeze().tolist()

    except Exception as _:
        print(f"Error processing SBERT for {alt_text}")
        sbert_score = 0  
    visual["alt_title"] = alt_text
    visual["sbert_score"] = sbert_score
    return visual

# def get_visual_scores(visual, max_score):
    """Ensure both clip_score and sbert_score exist before computing visual_score"""
    visual["clip_score"] = visual.get("clip_score", 0)
    visual["sbert_score"] = visual.get("sbert_score", 0)
    if (visual["sbert_score"] <= 0):
        visual["visual_score"] = visual["clip_score"]
    else:
        visual["visual_score"] = visual["clip_score"] * 0.2 + visual["sbert_score"] * 0.8
    max_score = max(max_score, visual["visual_score"])
    return visual, max_score

# def scaled_scores(visual, max_score):
    scalingFactor = 1- math.ceil(max_score *10)/10
    if(visual["visual_score"] >=0 and visual["visual_score"] < 0.3):
        visual["visual_score"] = round(visual["visual_score"]+0.1,3)
    else:
        visual["visual_score"] = round(scalingFactor + visual["visual_score"],3) 
    # print(f'{visual["alt_title"]}:{visual["visual_score"]}\n')
    image_alt_texts.append(visual["alt_title"]) 
    image_rel_scores.append(visual["visual_score"] )
    return visual

# def score_images(task, images):
    max_score = 0

    # task embedding using sbert
    task_embedding = sbert_model.encode(task, convert_to_tensor=True)

    # task embedding using CLIP
    text_inputs = processor(text=[task], return_tensors="pt", padding=True, truncation=True).to(DEVICE)

    with torch.no_grad():
        text_features = model.get_text_features(**text_inputs)
        text_features /= text_features.norm(dim=-1, keepdim=True)

    # Helper function to process one visual
    def process_single_visual(visual):
        try:
            visual = get_clip_scores(text_features, visual)
            visual = get_sbert_scores(task_embedding, visual)
            visual, _ = get_visual_scores(visual, 0)  
            return visual
        except Exception as e:
            print(f"Error processing visual: {e}")
            return {"clip_score": 0, "sbert_score": 0, "visual_score": 0, "error": str(e)}

    # Run in parallel using threads
    with ThreadPoolExecutor() as executor:
        raw_scores = list(executor.map(process_single_visual, images))

    # Compute max score for normalization
    max_score = max(v.get("visual_score", 0) for v in raw_scores)
    img_scores = [scaled_scores(v, max_score) for v in raw_scores]

    for visual in img_scores:
        if "visual_score" not in visual:
            visual["visual_score"] = 0 
    img_scores = [v for v in img_scores if "visual_score" in v]
    img_scores = sorted(img_scores, key=lambda x: x["visual_score"], reverse=True)

    print("image alt texts", image_alt_texts)
    print("image rel scores", image_rel_scores)

    return img_scores

def score_images(task, images):
    taskBreakdown = task_breakdown(task)

    def get_clip_score(text_features, visual):
        visual_url = visual.get("src", "")
        try:
            response = requests.get(visual_url, timeout=5)
            response.raise_for_status()
            with Image.open(BytesIO(response.content)) as image:
                if image.mode == "P":
                    image = image.convert("RGBA")
                else:
                    image = image.convert("RGB")
            image_inputs = processor(images=image, return_tensors="pt").to(DEVICE)
            with torch.no_grad():
                image_features = model.get_image_features(**image_inputs)
                image_features /= image_features.norm(dim=-1, keepdim=True)
            score = (image_features @ text_features.T).squeeze().item()
            visual["clip_score"] = score
        except Exception as e:
            # print(f"CLIP error for image {visual_url[:30]}...: {e}")
            visual["clip_score"] = 0
        return visual

    def score_image_batch(batch_index, batch, task, taskBreakdown, attempt=1):
        client = openai.OpenAI(api_key=api_key)
        numbered_alts = "\n".join([
            f"{i+1}. {img.get('alt') or img.get('title') or 'No description available'}"
            for i, img in enumerate(batch)
        ])

        prompt = f"""
        Given the user's task: "{task}" and the following task steps: {taskBreakdown}, evaluate the relevance of each image's alt text in helping the user complete their task.

        Score each image description (alt text) from 0 (irrelevant) to 100 (critical to the task). Return only an array of scores.

        Example output: [12, 87, 34, 0, 75]

        Alt texts to score:
        {numbered_alts}
        """

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an expert in image task relevance."},
                    {"role": "user", "content": prompt}
                ]
            )
            completion_text = response.choices[0].message.content.strip()
            # print_token_usage(response)

            if completion_text.startswith("```"):
                completion_text = completion_text.strip("` \n")
                if completion_text.startswith("json"):
                    completion_text = completion_text[4:].strip()
            scores = json.loads(completion_text.replace("'", '"'))

            if len(scores) != len(batch):
                raise ValueError(f"Expected {len(batch)} scores but got {len(scores)}")

            for i, score in enumerate(scores):
                batch[i]["gpt_score"] = score

            return batch, print_token_usage(response)


        except Exception as e:
            print(f"⚠️ GPT Batch {batch_index} failed on attempt {attempt}: {e}")
            if attempt < 3:
                time.sleep(1.5)
                return score_image_batch(batch_index, batch, task, taskBreakdown, attempt + 1)
            else:
                print(f"❌ GPT Batch {batch_index} failed after retries.")
                for img in batch:
                    img["gpt_score"] = 0
                # return batch
                return batch, {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "input_cost": 0.0,
                    "output_cost": 0.0,
                    "total_cost": 0.0
                }

    # embedding task with CLIP
    text_inputs = processor(text=[task], return_tensors="pt", padding=True, truncation=True).to(DEVICE)
    
    token_usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "input_cost": 0.0,
        "output_cost": 0.0,
        "total_cost": 0.0
    }

    
    with torch.no_grad():
        text_features = model.get_text_features(**text_inputs)
        text_features /= text_features.norm(dim=-1, keepdim=True)

    # getting CLIP scores - processing parallelly
    with ThreadPoolExecutor() as executor:
        images_with_clip = list(executor.map(lambda v: get_clip_score(text_features, v), images))

    # scoring relevance with GPT
    batches = [(batch_idx, images_with_clip[i:i + batch_size])
           for batch_idx, i in enumerate(range(0, len(images_with_clip), batch_size))]

    results = [None] * len(batches)
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(score_image_batch, batch_idx, b, task, taskBreakdown): batch_idx
            for batch_idx, b in batches
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                # results[index] = future.result()
                batch, usage = future.result()
                results[index] = batch
                for k in token_usage_totals:
                    token_usage_totals[k] += usage[k]

            except Exception as e:
                print(f"⚠️ Unexpected error in GPT batch {index}: {e}")
                results[index] = [{"gpt_score": 0} for _ in batches[index][1]]

    all_images = [img for batch in results if batch for img in batch]
    for img in all_images:
        img["clip_score"] = img.get("clip_score", 0)
        img["gpt_score"] = img.get("gpt_score", 0)
        if(img["gpt_score"] <= 0):
            img["visual_score"] = img["clip_score"]
        else:
            img["visual_score"] = round(0.3 * img["clip_score"] + 0.7 * (img["gpt_score"] / 100), 4)

    # sorting by visual_score
    all_images = sorted(all_images, key=lambda x: x["visual_score"], reverse=True)
    print("all images:", all_images) 

    print("🧾 Total image token usage:")
    print(f"Input tokens: {token_usage_totals['input_tokens']}")
    print(f"Output tokens: {token_usage_totals['output_tokens']}")
    print(f"Input cost: ${round(token_usage_totals['input_cost'], 6)}")
    print(f"Output cost: ${round(token_usage_totals['output_cost'], 6)}")
    print(f"Total cost: ${round(token_usage_totals['total_cost'], 6)}")


    return all_images


def get_svgs(svg_list):
    batches = [
        (batch_index, svg_list[start:start + batch_size])
        for batch_index, start in enumerate(range(0, len(svg_list), batch_size))
    ]

    results_by_index = [None] * len(batches)

    def process_batch(batch_index, batch):
        paths = [item["path"] for item in batch]
        names = identify_icon(batch_index, paths)
        for svg, name in zip(batch, names):
            svg["title"] = name
        return batch

    # Parallel execution
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_batch, idx, batch): idx
            for idx, batch in batches
        }

        for future in as_completed(futures):
            idx = futures[future]
            try:
                results_by_index[idx] = future.result()
            except Exception as e:
                print(f"⚠️ Unexpected error for batch {idx}: {e}")
                # Fill with "unknown"
                results_by_index[idx] = [
                    {**item, "title": "unknown"} for item in batches[idx][1]
                ]

    # Flatten the results
    final_result = []
    all_icon_names = []
    for batch_index, result_batch in enumerate(results_by_index):
        print(f"✅ Merging results from Batch {batch_index}")
        final_result.extend(result_batch)
        all_icon_names.extend([svg["title"] for svg in result_batch])

    print("\n🟢 All icon names in order:")
    print(all_icon_names)

    return final_result

def identify_icon(batch_index, paths, attempt=1):
    numbered_paths = "\n".join([f"{i+1}. {path}" for i, path in enumerate(paths)])

    prompt = (
        f"Given the following list of SVG paths, identify what each icon represents.\n"
        f"For each path, return a short name like 'search', 'close', 'menu', 'user', etc.\n"
        f"DO NOT add any other text. Only return a list of {len(paths)} names in this format: ['search', 'user', 'menu', ...]\n"
        f"SVG paths:\n{numbered_paths}"
    )

    client = openai.OpenAI(api_key=api_key)

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert in icon recognition."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
        )

        completion_text = response.choices[0].message.content.strip()
        # print(f"Batch {batch_index} Raw GPT output:", completion_text)

        # Cleanup if the model adds code formatting
        if completion_text.startswith("```"):
            completion_text = completion_text.strip("` \n")
            if completion_text.startswith("json"):
                completion_text = completion_text[4:].strip()

        completion_text = completion_text.replace("'", '"')
        icon_names = json.loads(completion_text)

        if not isinstance(icon_names, list):
            raise ValueError("Expected a list of icon names.")
        if len(icon_names) != len(paths):
            raise ValueError(f"Mismatch: got {len(icon_names)} names for {len(paths)} paths.")
        # print("icons:", icon_names)
        return icon_names
    

    except Exception as e:
        print(f"⚠️ Batch {batch_index} failed on attempt {attempt}: {e}")
        if attempt < 3:
            time.sleep(1.5)
            return identify_icon(batch_index, paths, attempt + 1)
        else:
            print(f"❌ Batch {batch_index} failed after 3 attempts. Returning 'unknown' list.")
            return ["unknown"] * len(paths)

def score_svg_batch(batch_index, batch, task, taskBreakdown, attempt=1):
    client = openai.OpenAI(api_key=api_key)
    numbered_elements = "\n".join([f"{i+1}. {svg['title']}" for i, svg in enumerate(batch)])

    prompt = f"""
    Given the user's task: "{task}" and the following task steps: {taskBreakdown}, you are interpreting the context of the current webpage from the icon titles given to you to understand which steps are meaningful and actionable from the breakdown of the user’s task.

    Score each icon title on a scale from 0 (irrelevant) to 100 (critical to the task).

    Prioritize scoring task-relevant icons higher, as the user must see them to successfully complete their task. Missing these icons would result in a poor experience, which this system aims to prevent.

    Return only an array with {len(batch)} scores. Do NOT include any explanation, notes, or additional text.

    Example output format: [12, 87, 34, 0, 75]

    Icons to score: {numbered_elements}
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert task evaluator."},
                {"role": "user", "content": prompt}
            ]
        )

        completion_text = response.choices[0].message.content.strip()

        # print_token_usage(response)


        if completion_text.startswith("```"):
            completion_text = completion_text.strip("` \n")
            if completion_text.startswith("json"):
                completion_text = completion_text[4:].strip()

        completion_text = completion_text.replace("'", '"')
        scores = json.loads(completion_text)

        if not isinstance(scores, list):
            raise ValueError("Expected a list of scores.")
        if len(scores) != len(batch):
            raise ValueError(f"Mismatch: got {len(scores)} scores for {len(batch)} elements.")

        return scores, print_token_usage(response)

    except Exception as e:
        print(f"⚠️ Batch {batch_index} failed on attempt {attempt}: {e}")
        if attempt < max_retries:
            time.sleep(1.5)
            return score_svg_batch(batch_index, batch, task, taskBreakdown, attempt + 1)
        else:
            print(f"❌ Batch {batch_index} failed after {max_retries} attempts. Filling with 0s.")
            # return [0] * len(batch)
            return [0] * len(batch), {
                "input_tokens": 0,
                "output_tokens": 0,
                "input_cost": 0.0,
                "output_cost": 0.0,
                "total_cost": 0.0
            }


def score_svgs(task, svg):
    taskBreakdown = task_breakdown(task)

    batches = [
        (batch_index, svg[batch_start:batch_start + batch_size])
        for batch_index, batch_start in enumerate(range(0, len(svg), batch_size))
    ]

    # --- Score each SVG batch ---
    results_by_index = [None] * len(batches)

    token_usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "input_cost": 0.0,
        "output_cost": 0.0,
        "total_cost": 0.0
    }

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(score_svg_batch, idx, batch, task, taskBreakdown): idx
            for idx, batch in batches
        }

        for future in as_completed(futures):
            idx = futures[future]
            try:
                # results_by_index[idx] = future.result()
                scores, usage = future.result()
                results_by_index[idx] = scores
                for k in token_usage_totals:
                    token_usage_totals[k] += usage[k]

            except Exception as e:
                print(f"⚠️ Scoring batch {idx} failed: {e}")
                results_by_index[idx] = [0] * len(batches[idx][1])

    # --- Combine results ---
    scored_svgs = []
    all_scores_flat = []
    # all_labels_flat = []

    for (batch_index, batch), scores in zip(batches, results_by_index):
        for svg_dict, score in zip(batch, scores):
    # for (batch_index, batch), scores, labels in zip(batches, results_by_index, label_results):
    #     for svg_dict, score, label in zip(batch, scores, labels):
            normalized_score = score / 100
            svg_dict["score"] = normalized_score
            # svg_dict["label"] = label
            scored_svgs.append(svg_dict)
            all_scores_flat.append(normalized_score)
            # all_labels_flat.append(label)

    # --- Print outputs ---
    print("\n🟢 All SVG scores:")
    print(all_scores_flat)

    print("🧾 Total SVG token usage:")
    print(f"Input tokens: {token_usage_totals['input_tokens']}")
    print(f"Output tokens: {token_usage_totals['output_tokens']}")
    print(f"Input cost: ${round(token_usage_totals['input_cost'], 6)}")
    print(f"Output cost: ${round(token_usage_totals['output_cost'], 6)}")
    print(f"Total cost: ${round(token_usage_totals['total_cost'], 6)}")


    # print("\n🏷️ All SVG labels:")
    # print(all_labels_flat)

    return scored_svgs



if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)



