from http import client
from flask import Flask, request, jsonify
from flask_cors import CORS
from sentence_transformers import SentenceTransformer, util
import time
import torch
import numpy as np
import json 
import os
import openai
from concurrent.futures import ThreadPoolExecutor, as_completed
import tiktoken


GPT4O_INPUT_COST_PER_1K = 0.005
GPT4O_OUTPUT_COST_PER_1K = 0.015

app = Flask(__name__)
CORS(app)

api_key = os.environ["OPENAI_API_KEY"]


# compute normalized OpenAI GPT scores
def compute_openai_scores(api_key, task, text_tag, batch_size=50, max_workers=5, max_retries=3):
    start_time = time.time()  
    client = openai.OpenAI(api_key=api_key) 
    
    encoding = tiktoken.encoding_for_model("gpt-4o")

    # Combine all prompts into one string for accurate input count
    total_input_text = f"{task}\n\n" + "\n".join([el["text"] for el in text_tag])
    input_tokens = len(encoding.encode(total_input_text))

    


    def task_breakdown(task):
        prompt1 = f"""
        Given the user's task: "{task}", break it down into the following components to help identify and prioritize relevant page elements:

        1. entity: the main object or item the user is interested in
        2. constraints: broad category of requirements or preferences (e.g., cost, color, brand, filter categories) 
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
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an expert task evaluator."},
                    {"role": "user", "content": prompt1}
                ],
                temperature = 0.5
            )
            taskBreakdown = response.choices[0].message.content.strip()
            print("Task breakdown:", taskBreakdown)
            return taskBreakdown

        except Exception as e:
            return {"error": f"Task breakdown failed: {e}"}

    def normalize(scores):
        return [round(min(max(score / 100.0, 0), 1), 3) for score in scores]
    
    taskBreakdown = task_breakdown(task)

    def score_batch(batch_index, batch, attempt=1):
        numbered_elements = "\n".join([f"{i+1}. {t}" for i, t in enumerate(batch)])

        prompt2= f"""
            User Task: "{task}"
            Task Steps: {taskBreakdown}

            You are interpreting the webpage from a list of text elements to determine which are relevant for completing the user’s task. Do not evaluate elements in isolation. Instead, consider their surrounding elements and whether they belong to a structured unit or repeated group (like a product card, listing, or section).
            If one element in a unit strongly matches the task (e.g., product title, price, size), you should score associated elements (e.g., “Add to cart”, “each”, or “$/oz”) accordingly based on how much they contribute to helping the user complete the task.
            Score each element on a scale from 0 (irrelevant) to 100 (critical to the task).

            Key guidelines:
                1. Interpret structured groups (cards) from the tags of texts. Treat structured groups as semantic units. Score inner elements similarly only if the card as a whole is relevant.
                2. Match all task constraints (e.g., flavor, price, size, pickup availability). If 2–3 constraints are satisfied, the card is still relevant.
                3. Score repeated actions (like “Add to cart” or “Add to list”) only if tied to a relevant card.
                4. Penalize loose, standalone text (titles, prices, buttons) that are not clearly part of a relevant group.
                5. If missing the element would prevent task success, assign a high score.

            You may infer relationships based on text proximity, matching patterns, and card repetition structure.
            Return only an array with {len(batch)} scores. No explanation.
            Example format: [12, 87, 34, 0, 75]
            Text elements to score: {numbered_elements}
        """

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                # model="gpt-4o-mini",
                # model = "o1-2024-12-17",
                messages=[
                    {"role": "system", "content": "You are an expert task evaluator."},
                    {"role": "user", "content": prompt2}
                ],
                temperature = 0.3
            )

            completion_text = response.choices[0].message.content.strip()
            print(f"Batch {batch_index} Raw GPT output:", completion_text)

            if completion_text.startswith("```"):
                completion_text = completion_text.strip("` \n")
                if completion_text.startswith("json"):
                    completion_text = completion_text[4:].strip()

            scores = json.loads(completion_text)

            if not isinstance(scores, list):
                raise ValueError("Expected a list of scores.")
            if len(scores) != len(batch):
                raise ValueError(f"Mismatch: got {len(scores)} scores for {len(batch)} elements.")

            return normalize(scores)

        except Exception as e:
            print(f"⚠️ Batch {batch_index} failed on attempt {attempt}: {e}")
            if attempt < max_retries:
                time.sleep(1.5)  # backoff
                return score_batch(batch_index, batch, attempt + 1)
            else:
                print(f"❌ Batch {batch_index} failed after {max_retries} attempts. Filling with 0s.")
                return [0] * len(batch)

    batches = [
        (batch_index, text_tag[batch_start:batch_start + batch_size])
        for batch_index, batch_start in enumerate(range(0, len(text_tag), batch_size))
    ]

    results_by_index = [None] * len(batches)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(score_batch, idx, batch): idx
            for idx, batch in batches
        }

        for future in as_completed(futures):
            idx = futures[future]
            try:
                results_by_index[idx] = future.result()
            except Exception as e:
                print(f"⚠️ Unexpected error for batch {idx}: {e}")
                results_by_index[idx] = [0] * len(batches[idx][1])  # fallback

    # Combine results in order and log batch merging
    all_scores = []
    for batch_index, batch_scores in enumerate(results_by_index):
        print(f"✅ Merging scores from Batch {batch_index} into final list.")
        all_scores.extend(batch_scores)

    print("All GPT scores:", all_scores)

    # Print tag-text-score triples
    for item, score in zip(text_tag, all_scores):
        print({"tag": item["tag"], "text": item["text"], "score": score})

    end_time = time.time()
    print(f"\nCompleted scoring {len(text_tag)} elements in {round(end_time - start_time, 2)} seconds.")


    # Estimate output tokens from each response (rough estimate)
    output_texts = [str(score) for score in all_scores]  # single array like "[12, 90, 45...]"
    output_tokens = len(encoding.encode(json.dumps(output_texts)))

    # Cost estimation
    input_cost = (input_tokens / 1000) * GPT4O_INPUT_COST_PER_1K
    output_cost = (output_tokens / 1000) * GPT4O_OUTPUT_COST_PER_1K
    total_cost = input_cost + output_cost

    print(f"Input tokens: {input_tokens}, Output tokens: {output_tokens}, Input cost:  ${input_cost:.6f}, Output cost:  ${output_cost:.6f},Total cost: ${total_cost:.6f}")


    return all_scores
    # return {
    # "scores": all_scores,
    # "input_tokens": input_tokens,
    # "output_tokens": output_tokens,
    # "input_cost": input_cost,
    # "output_cost": output_cost,
    # "total_cost": total_cost
    # }


# computing final scores based on GPT 
def compute_final_scores(gpt_scores):
    gpt_scores = [float(gpt_scores[i]) if i < len(gpt_scores) else 0.0 for i in range(len(gpt_scores))]
    final = [round(g, 3) for g in gpt_scores]
    return final



@app.route('/process_elements', methods=['POST'])
def process_elements():
    try:
        data = request.json
        user_task = data.get('task', "")
        elements_map = data.get('elementsMap', [])

        print("Received task:", user_task, "Elements count:", len(elements_map))

        if not user_task or not elements_map:
            return jsonify({"error": "Missing task or elementsMap"}), 400

        # Find elements with text
        to_score_indices = [
            i for i, el in enumerate(elements_map)
            if isinstance(el.get("text", ""), str) and len(el["text"].strip()) > 2
        ]
        text_tag_elements_to_score = [
            {
                "tag": elements_map[i].get("tag", "").strip(),
                "text": elements_map[i].get("text", "").strip()
            }
            for i in to_score_indices
        ]

        print("length of text_elements_to_score:", len(text_tag_elements_to_score))
        # print("Text elements to score:", text_tag_elements_to_score)

        texts_only = [el["text"] for el in text_tag_elements_to_score]
        print("Texts only:")
        print(texts_only)

        # Compute scores and labels
        gpt_norm = compute_openai_scores(api_key, user_task, text_tag_elements_to_score)
        # gpt_label = compute_openai_labels(api_key, user_task, text_tag_elements_to_score)

        if isinstance(gpt_norm, dict) and "error" in gpt_norm:
            return jsonify({"error": f"GPT scoring failed: {gpt_norm['error']}"}), 500

        # gpt_norm = gpt_result["scores"]
        final_scores = compute_final_scores(gpt_norm)

        for el in elements_map:
            el["gptScore"] = 0.0
            el["score"] = 0.0
            el["relevant"] = False

        for idx, original_idx in enumerate(to_score_indices):
            elements_map[original_idx]["gptScore"] = gpt_norm[idx]
            elements_map[original_idx]["score"] = final_scores[idx]
            # elements_map[original_idx]["label"] = gpt_label[idx]

        # print({
        #     "tokenUsage": {
        #         "input_tokens": gpt_norm["input_tokens"],
        #         "output_tokens": gpt_norm["output_tokens"],
        #         "input_cost": round(gpt_norm["input_cost"], 6),
        #         "output_cost": round(gpt_norm["output_cost"], 6),
        #         "total_cost": round(gpt_norm["total_cost"], 6)
        #     }
        # })
        
        elements_map.sort(key=lambda x: x["score"], reverse=True)

        return jsonify({"elementsMap": elements_map})

    except Exception as e:
        return jsonify({"error": f"Processing failed: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)




# computing normalized SBERT similarity scores
# def compute_sbert_scores(task, texts, model):
#     if not texts:
#         return [0] * len(texts)

#     task_embedding = model.encode(task, convert_to_tensor=True)

#     def batch_encode(texts, batch_size=256):
#         embeddings = []
#         for i in range(0, len(texts), batch_size):
#             batch = texts[i:i+batch_size]
#             batch_embeds = model.encode(batch, convert_to_tensor=True)
#             embeddings.append(batch_embeds)
#         return torch.cat(embeddings, dim=0)

#     text_embeddings = batch_encode(texts)
#     similarity_scores = util.pytorch_cos_sim(task_embedding, text_embeddings).squeeze().tolist()

#     min_s, max_s = min(similarity_scores, default=0), max(similarity_scores, default=1)
#     normalized = [round((s - min_s) / (max_s - min_s + 1e-8), 2) for s in similarity_scores]

#     print("Normalized SBERT scores:", normalized)
#     return normalized

# compute normalized BERTScore F1 similarity scores
# def compute_bert_scores(task, texts, scorer):
#     if not texts:
#         return [0] * len(texts)

#     _, _, F1 = scorer.score(texts, [task] * len(texts))
#     scores = F1.cpu().tolist()

#     min_b, max_b = min(scores, default=0), max(scores, default=1)
#     normalized = [round((b - min_b) / (max_b - min_b + 1e-8),2) for b in scores]
#     print("Normalized BERT scores:", normalized)
#     return normalized


# def compute_openai_labels(api_key, task, text_tag, batch_size=50, max_workers=5, max_retries=3):
#     client = openai.OpenAI(api_key=api_key)

#     def label_batch(batch_index, batch, attempt=1):
#         numbered_elements = "\n".join([f"{i+1}. {el['text']}" for i, el in enumerate(batch)])

#         prompt = f"""
#         You are a task evaluator. The user’s task is: "{task}"

#         Label each of the following text elements as **Essential**, **Optional**, or **Irrelevant** to the user’s based on its relevance to complete the task.

#         Definitions:
#         - **Essential (E)**: The task cannot be completed without this element. (e.g., “Add to cart” button, search bar, price of relevant product)
#         - **Optional (O)**: The element may help but is not required. (e.g., reviews, comparisons, extra filters)
#         - **Irrelevant (I)**: The element does not help complete the task. (e.g., unrelated ads, menu tabs for other categories)

#         Return a list of labels only, like:
#         ["E", "O", "I", ...]

#         Elements to label:
#         {numbered_elements}
#         """

#         try:
#             response = client.chat.completions.create(
#                 model="o1-2024-12-17",  
#                 messages=[
#                     {"role": "system", "content": "You are a helpful assistant that classifies webpage elements."},
#                     {"role": "user", "content": prompt}
#                 ]
#             )

#             content = response.choices[0].message.content.strip()

#             if content.startswith("```"):
#                 content = content.strip("` \n")
#                 if content.startswith("json"):
#                     content = content[4:].strip()

#             labels = json.loads(content)
#             assert isinstance(labels, list) and len(labels) == len(batch)
#             return labels

#         except Exception as e:
#             print(f"⚠️ Batch {batch_index} failed on attempt {attempt}: {e}")
#             if attempt < max_retries:
#                 time.sleep(1.5)
#                 return label_batch(batch_index, batch, attempt + 1)
#             else:
#                 return ["Irrelevant"] * len(batch)

#     # Split into batches
#     batches = [
#         (batch_index, text_tag[batch_start:batch_start + batch_size])
#         for batch_index, batch_start in enumerate(range(0, len(text_tag), batch_size))
#     ]

#     results_by_index = [None] * len(batches)

#     with ThreadPoolExecutor(max_workers=max_workers) as executor:
#         futures = {
#             executor.submit(label_batch, idx, batch): idx
#             for idx, batch in batches
#         }

#         for future in as_completed(futures):
#             idx = futures[future]
#             try:
#                 results_by_index[idx] = future.result()
#             except Exception as e:
#                 print(f"❌ Unexpected error for batch {idx}: {e}")
#                 results_by_index[idx] = ["Irrelevant"] * len(batches[idx][1])

#     # Flatten results
#     all_labels = []
#     for batch_index, batch_labels in enumerate(results_by_index):
#         print(f"✅ Merging labels from Batch {batch_index} into final list.")
#         all_labels.extend(batch_labels)

#     print("All GPT labels:", all_labels)
#     print("Labels count:" , len(all_labels))
#     return all_labels


