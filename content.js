let textScoresMap = {};
let imageScoresMap = {};
let svgScoresMap = {};
let visualReady = false;
let textReady = false;
let elementsTree = [];
let task = "";

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.message === 'processTask') {
    task = request.data;
    processWebPage(request.data, request.parameters);
    sendResponse({ reply: 'Received task in CS.' });
  }
});

// check for injected content script
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.message === 'inject') {
      sendResponse({ reply: 'Already injected' });
    }
});

// function to process webpage elements
function processWebPage(task, parameters) {

    let imageData = [];
    let svgData = [];
    let iframeData = [];
    let idCounter = 0;
    let rootNode = null;
    task = task;

    // obtain text in node
    function getDirectText(element) {
        let text = "";
        for (let child of element.childNodes) {
            if (child.nodeType === Node.TEXT_NODE) {
                text += child.textContent.trim() + " ";
            }
        }
        return text.trim();
    }
    
    // traverse DOM to collect text and image nodes
    function traverseDOM(element, parentID = null) {
        if (!element || element.tagName === "SCRIPT" || element.tagName === "STYLE"  || element.tagName === "NOSCRIPT")  return null;

        let elementID = `elem-${idCounter++}`; 
        element.setAttribute("data-unique-id", elementID);
        
        let node = {
            id: elementID,
            tag: element.tagName,
            text: getDirectText(element),
            href: element.href || null,
            parentID: parentID,
            children: [],
            relevant: false
        };

        if (element.tagName === "IMG") {
            node.src = element.src || null;
            node.alt = element.alt || null;
            imageData.push({ id: elementID, src: node.src, alt: node.alt });
        }

        if (element.tagName?.toUpperCase() === "SVG") {
          node.title = element.title || null;
          path = element.querySelector("path");
          node.path = path?.getAttribute("d") || null;
          svgData.push({ id: elementID, title: node.title, path: node.path });
        }
        

        if (element.tagName === "IFRAME") {
            node.src = element.src || null;
            node.title = element.title || null;
            iframeData.push({ id: elementID, src: node.src, alt: node.alt });
        }

        elementsTree.push(node);

        for (let child of element.children) {
            let childNode = traverseDOM(child, elementID);
            if (childNode) node.children.push(childNode);
        }
        return node;
    }

    rootNode = traverseDOM(document.body);
    
    // processing visual elements
    chrome.runtime.sendMessage(
      {
        action: "processVisuals",
        images: imageData,
        iframes: iframeData,
        svg: svgData,
        task: task
      },
      (response) => {
        if (chrome.runtime.lastError) {
            console.warn("Media message not delivered:", chrome.runtime.lastError);
        } else if (response && response.img_scores && response.svg_scores) {
            imageScores = response.img_scores;
            svgScores = response.svg_scores;
            imageScores.forEach((item) => {
                imageScoresMap[item.id] = {
                  tag: "IMG",
                  score: item.visual_score,
                  clip_score: item.clip_score,
                  sbert_score: item.sbert_score
                };
            });
            svgScores.forEach((item) => {
                svgScoresMap[item.id] = {
                  tag: "svg",
                  title: item.title,
                  score: item.score
                };
            });

            visualReady = true;
            tryUpdateDOM(parameters, task);
        } else {
          console.warn("Unexpected response:", response);
          // console.log("imageScoresMap:", imageScoresMap);
          visualReady = true;
          tryUpdateDOM(parameters, task);
        }
      }
    );

    // processing text elements
    chrome.runtime.sendMessage(
      { action: "processTexts", data: elementsTree, task: task },
      (textResponse) => {
        if (chrome.runtime.lastError) {
          console.warn("Text message not delivered:", chrome.runtime.lastError);
        } else if (textResponse && textResponse.data) {
          textResponse.data.elementsMap.forEach((item) => {
            textScoresMap[item.id] = {
              tag: item.tag,
              score: item.score
            };
          });
          textReady = true;
          tryUpdateDOM(parameters, task);
        } else {
          console.warn("Unexpected text response:", textResponse);
          textReady = true;
          tryUpdateDOM(parameters, task);
        }
      }
    )
}

// function to update DOM based on scores
function tryUpdateDOM(parameters, task) {
  let maxScore = 0
  let maxScoreId = ""
  if (visualReady && textReady) {
    elementsTree.forEach((node) => {
      node.score = 0;
      if (node.tag === "IMG" && imageScoresMap[node.id].tag === "IMG") {
        node.gpt_score = imageScoresMap[node.id].gpt_score;
        node.clip_score = imageScoresMap[node.id].clip_score;
        node.score = imageScoresMap[node.id].score;
      } else if (node.tag?.toLowerCase() === "svg" && svgScoresMap[node.id]) {
        node.score = svgScoresMap[node.id].score;
        node.title = svgScoresMap[node.id].title;
      } else if (node.tag === "IFRAME") {
        node.score = -1;
      } else if (textScoresMap[node.id]) {
        node.score = textScoresMap[node.id].score;
      } 
      
      // marking relevant nodes
      if (parameters.displayStyle === "task-specific") {
        node.relevant = node.score >= parameters.relevanceThreshold / 100;
      } else if (["color-gradient", "less-opacity"].includes(parameters.displayStyle)) {
        node.relevant = node.score >= 0;
      }
      
      if (maxScore <= node.score) {
        maxScore = node.score
        maxScoreId = node.id
      }
    });


    
    const parentMap = {};
    elementsTree.forEach(el => parentMap[el.id] = el);

    // Find all relevant nodes (excluding IMG and SVG) with a score above the threshold
    let relevantTextNodes = elementsTree.filter(n => 
      n.tag !== "IMG" && n.tag !== "svg" && n.relevant && n.score > 0.6
    );
    
    const imageScores = [];

    elementsTree.forEach(node => {
      if (node.tag === "IMG") {
        // Calculate the proximity threshold dynamically based on the image size
        let proximityThreshold = 0;
    
        // Check if node is a DOM element and get its bounding rect
        let imageElement = document.querySelector(`[data-unique-id='${node.id}']`);
        if (imageElement) {
          const imageRect = imageElement.getBoundingClientRect();
          const imageWidth = imageRect.width;
          const imageHeight = imageRect.height;
          proximityThreshold = Math.max(imageWidth, imageHeight) * 1; // Set threshold as 20% of image's size
        }
    
        
        let nearbyTextNodes = relevantTextNodes.filter(textNode => {
          let distance = calculateDistance(node, textNode);
          return distance < proximityThreshold;
        });
      
        // Step 2: Boost score only if more than 2 relevant nodes are nearby
        if (node.score >= 0.25 && nearbyTextNodes.length >2) {
          const previousScore = node.score;
          // Optional: use the max score among nearby nodes or the average
          const maxNearbyScore = Math.max(...nearbyTextNodes.map(n => n.score));
          node.score = Math.max(maxNearbyScore, 0.4 * node.score + 0.6 * Math.max(node.score, 0.7));
          console.log("Image score updated due to nearby text nodes:", node.id, node.score, previousScore);
        }
         else if (nearbyTextNodes.length === 0) {
            node.score = 0;
        }
        imageScores.push(node.score);
  
      }
    })

    console.log("📊 Corresponding image scores:", imageScores);

    function propagateRelevanceUpward(el) {
      if (el.parentID && parentMap[el.parentID]) {
        const parent = parentMap[el.parentID];
        if (!parent.relevant) {
          parent.relevant = true;
          propagateRelevanceUpward(parent);
        }
      }
    }

    function propagateScoreUpward(el) {
      if (el.parentID && parentMap[el.parentID]) {
        const parent = parentMap[el.parentID];
        if (parent.score < el.score) {
          parent.score = el.score;
          propagateScoreUpward(parent);
        }
      }
    }

    if (parameters.displayStyle === "task-specific") {
      elementsTree.forEach(el => el.relevant && propagateRelevanceUpward(el));
    } else if (parameters.displayStyle === "less-opacity") {
      elementsTree.forEach(el => el.relevant && propagateScoreUpward(el));
    }

    elementsTree.forEach(el => {
      if (el.children?.length) {
        el.children.forEach(child => {
          const childRef = parentMap[child.id];
          if (childRef) {
            child.score = childRef.score;
          }
        });
      }
    });

    // updating DOM based on scores
    elementsTree.forEach(node => updateDOMVisibility(node, parameters, maxScore));
    chrome.runtime.sendMessage({ action: 'page-updated' });
    console.log("Page updated!");
  }
}

function calculateDistance(imageNode, textNode) {
  // Ensure both nodes are DOM elements
  const imageElement = document.querySelector(`[data-unique-id='${imageNode.id}']`);
  const textElement = document.querySelector(`[data-unique-id='${textNode.id}']`);

  if (imageElement && textElement) {
    const imageRect = imageElement.getBoundingClientRect();
    const textRect = textElement.getBoundingClientRect();

    // Center of the image
    const imageCenterX = imageRect.left + imageRect.width / 2;
    const imageCenterY = imageRect.top + imageRect.height / 2;

    // Find closest point on the text element's box to the image center
    const closestX = Math.max(textRect.left, Math.min(imageCenterX, textRect.right));
    const closestY = Math.max(textRect.top, Math.min(imageCenterY, textRect.bottom));

    // Euclidean distance from image center to closest point on text element
    const dx = imageCenterX - closestX;
    const dy = imageCenterY - closestY;

    return Math.sqrt(dx * dx + dy * dy);
  }

  return Infinity;
}

// function to update DOM visibility based on scores
function updateDOMVisibility(node, parameters, maxScore) {
  let element = document.querySelector(`[data-unique-id='${node.id}']`);
  if (!element) return;
  if (parameters.displayStyle === "task-specific") {
    if (!node.relevant) {
        element.style.display = "none";
        element.style.pointerEvents = "none";
        element.setAttribute("aria-hidden", "true");
    }
  }
  else if(parameters.displayStyle === "color-gradient") {
    score = Math.max(0, Math.min(node.score, 1));
    const colors = [
        "#ffffff", // scores 0.0 - 0.1
        // "#ffffff", // 0.1 - 0.2
        "#ebfce8", // 0.2 - 0.3
        // "#fff5b3", // 0.2 - 0.3
        "#fff5b3", // 0.3 - 0.4
        "#e6f598", // 0.4 - 0.5
        // "#fee08b", // 0.4 - 0.5
        "#fee08b", // 0.5 - 0.6
        "#fdae61", // 0.6 - 0.7
        // "#f46d43", // 0.6 - 0.7
        "#f46d43", // 0.7 - 0.8
        "#9e0142", // 0.8 - 0.9
        // "#9e0142", // 0.8 - 0.9
        "#70161E"  // 0.9 - 1.0
        
    ];
  
    // mapping the score to a color from the palette
    const colorIndex = Math.floor(score * (colors.length - 1));
    borderColor = colors[colorIndex];
    element.style.border = `3px solid ${borderColor}`;
    if(colorIndex == 0 || colorIndex == 1) {
      element.style.borderColor = "transparent";
    }
    element.style.pointerEvents = "auto";
    element.setAttribute("aria-hidden", "false");
  }
  else if (parameters.displayStyle === "less-opacity") {
      scalingFactor = Math.floor(maxScore * 10) / 10;
      // console.log("maxscore-scaling factor", maxScore, scalingFactor)
      score = Math.max(0, Math.min(node.score, 1));
      if(score >= 0 && score < 0.4)
        element.style.opacity = score + 0.5;
      // ******
      // else element.style.opacity = (1-scalingFactor) + score;
      else {
        element.style.opacity = 2 * score;
        // ******
        // console.log("after bosting opacity - nodeID , score, opacity", node.id, score, element.style.opacity)
      } 
      // element.style.opacity  = score;
      element.style.pointerEvents = "auto";
      element.setAttribute("aria-hidden", "false");
  }
}

// function to update the display style
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.message === 'updateDisplayStyle') {
    parameters = request.parameters;
    task = request.task;
    console.log("Updated display style in content script:", parameters);
    clearPreviousStyling();
    tryUpdateDOM(parameters, task)
    sendResponse({ reply: 'Display style updated!' });
  }
});

// function to clear previous styling
function clearPreviousStyling() {
  const allElements = document.querySelectorAll("*");
  elementsTree.forEach(el => el.relevant = false);
  // console.log("elementsTree in clearPreviousStyling()", elementsTree)

  allElements.forEach(el => {
    el.style.opacity = '';
    el.style.filter = '';
    el.style.backgroundColor = '';
    el.style.border = '';
    el.style.outline = '';
    el.style.pointerEvents = '';
    el.setAttribute("aria-hidden", "false");
    el.style.display = '';
  });
}
