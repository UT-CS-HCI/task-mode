let taskWindowId = null;
let lastPageTabId = null;
let taskActive = false;
let currentTaskData = null;
let contentWindowId = null;

let parameters = null;


// creates a chrome extension popup window
chrome.action.onClicked.addListener((tab) => {
    lastPageTabId = tab.id; 
    contentWindowId = tab.windowId;
    if (taskWindowId) {
        chrome.windows.update(taskWindowId, { focused: true });
    } else {
        chrome.windows.create({
            url: chrome.runtime.getURL("interface.html"),
            type: "popup",
            width: 400,
            height: 500
        }, (window) => {
            taskWindowId = window.id;
        });
    }
});

// forwarding task data from interface to content script
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.message === 'taskUpdate') {
    currentTaskData = request.data;
    parameters = request.parameters;
    taskActive = true;
    if (lastPageTabId != null) {
              chrome.tabs.sendMessage(
          lastPageTabId,
          { message: 'processTask', data: currentTaskData, parameters: parameters },
          (response) => {
            if (response) {
              console.log('Background received response from content:', response.reply);
            }
          }
        );
    } else {
      console.warn("No valid non-extension tab available to inject content script.");
    }
    sendResponse({ reply: 'BG here. Msg sent to CS.' });
  }
  return true;
});

// change observer when the user switches to another tab
chrome.tabs.onActivated.addListener((activeInfo) => {
  chrome.tabs.get(activeInfo.tabId, (tab) => {
    if (tab.url &&
        !tab.url.startsWith('chrome://') &&
        !tab.url.startsWith('chrome-extension://')) {
      lastPageTabId = activeInfo.tabId;
    }
  });
});

// close the popup window when the task is completed
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.message === 'task-completed') {
        taskActive = false;
        // taskTabId = null;
        return;
    }
})

// check if the content script is injected
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (changeInfo.status === 'complete') {
        if (taskActive  && tab.url && !tab.url.startsWith('chrome://') &&  !tab.url.startsWith('chrome-extension://')) {
            chrome.tabs.sendMessage( tabId, { message: 'inject' },(response) => {
                if (response) {
                    console.log('Background received response from content 2222:', response.reply);
                    chrome.tabs.sendMessage(
                        tabId,
                        { message: 'processTask', data: currentTaskData, parameters: parameters },
                        (response) => {
                            if (chrome.runtime.lastError) {
                                console.warn('Message failed on tab', tabId, chrome.runtime.lastError.message);
                            } else if (response) {
                                console.log('Task update processed in tab', tabId, response.reply);
                            }
                        }   
                    );
                }                          
            })
        }
    }
})

// change the display style of the task-relevant elements
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.message === 'updateDisplayStyle') {
        parameters = request.parameters;
        if (lastPageTabId != null) {
            chrome.tabs.sendMessage(
                lastPageTabId,
                { message: 'updateDisplayStyle', parameters: parameters },
                (response) => {
                    if (response) {
                        console.log('Background received response from content:', response.reply);
                    }
                }
            );
        } else {
            console.warn("No valid non-extension tab available to inject content script.");
        }
        sendResponse({ reply: 'Display style updated in background!' });
    }
})

// processing text with flask
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.action === "processTexts") {

        fetch("http://127.0.0.1:5000/process_elements", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                task: message.task,
                elementsMap: message.data
            })
        })
        .then(response => response.json())
        .then(data => {
            console.log("Text scores from flask:", data);
            sendResponse({ data });
        })
        .catch(error => {
            console.error("Error forwarding data:", error);
            sendResponse({ error: "Failed to send data" });
        });
        return true; 
    }
});

// processing visuals with flask
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.action === "processVisuals") {
        fetch("http://127.0.0.1:5001/process_visuals", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                task: message.task,
                images: message.images,
                // iframes: message.iframes,
                svg: message.svg
            })
        })
        .then(response => response.json())
        .then(data => {
            console.log("Visual scores from flask:", data);
            sendResponse(data);
        })
        .catch(error => {
            console.error("Error forwarding data:", error);
            sendResponse({ error: "Failed to send data to Flask" });
        });
        return true; 
    }
});
