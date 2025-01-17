function xformAjaxAdapter (formSpec, sessionData, savedInstance, ajaxfunc, submitfunc, presubmitfunc,
                           render_context, answerCallback) {
  var self = this;
  this.formSpec = formSpec;
  this.sessionData = sessionData;
  this.session_id = null;
  this.ajaxfunc = ajaxfunc;
  this.submitfunc = submitfunc;
  this.presubmitfunc = presubmitfunc;
  this.render_context = render_context;
  this.answerCallback = answerCallback;

  $.unsubscribe([
      'formplayer.submit-form',
      'formplayer.delete-repeat',
      'formplayer.new-repeat',
      'formplayer.answer-question',
      'formplayer.evaluate-xpath'
  ].join(' '));
  $.subscribe('formplayer.submit-form', function(e, form) {
      if (!self.presubmitfunc()) { return; }
      self.submitForm(form);
  });
  $.subscribe('formplayer.delete-repeat', function(e, group) {
      self.deleteRepeat(group);
  });
  $.subscribe('formplayer.new-repeat', function(e, repeat) {
      self.newRepeat(repeat);
  });
  $.subscribe('formplayer.answer-question', function(e, question) {
      self.answerQuestion(question);
  });
  $.subscribe('formplayer.evaluate-xpath', function(e, xpath, callback) {
      self.evaluateXPath(xpath, callback);
  });

  this.loadForm = function ($div, init_lang, onload, onerror) {
    var args = {
      'action': 'new-form',
      'instance-content': savedInstance,
      'lang': init_lang,
      'session-data': this.sessionData,
      'nav': 'fao'
    };
    var form_param = {uid: 'form-name', raw: 'form-content', url: 'form-url'}[this.formSpec.type];
    args[form_param] = this.formSpec.val;
        
    // handle preloaders (deprecated) for backwards compatibilty
    if (args['session-data'] && args['session-data'].preloaders) {
      if (args['session-data'] == null) {
        args['session-data'] = {};
      }
      args['session-data'].preloaders = init_preloaders(args['session-data'].preloaders);
    }
        
    this.initForm(args, $div, onload, onerror);
  }

  this.resumeForm = function(session_id, $div, onload, onerror) {
    var args = {
      "action": "current",
      "session-id": session_id
    };

    this.session_id = session_id;
    this.initForm(args, $div, onload, onerror);
  }

  this.initForm = function(args, $div, onload, onerror) {
    var adapter = this;
    this.ajaxfunc(args, function (resp) {
      // special case short circuiting errors
      if (resp.status === "error" || resp.error) {
        if (!resp.message) {
          resp.message = resp.error;
        }
        if (onerror) {
          onerror(resp);
        }
        return;
      }
      if (!adapter.session_id) { // already know session id for resumed sessions
        adapter.session_id = resp["session_id"];
        console.log('session id: ' + adapter.session_id);
      }
      adapter.form = Formplayer.Utils.initialRender(resp, self.render_context.resourceMap, $div);
      if (onload) {
        onload(adapter, resp);
      }
    });
  }

  this.answerQuestion = function (q) {
    var self = this;
    var ix = getIx(q);
    var answer = q.answer();

    var adapter = this;
    this.ajaxfunc({'action': 'answer',
                   'session-id': this.session_id,
                   'ix': ix,
                   'answer': answer},
      function (resp) {
          $.publish('adapter.reconcile', [resp, q]);
          if (self.answerCallback !== undefined) {
              self.answerCallback(self.session_id);
          }
      });

  };

  this.evaluateXPath = function(xpath, callback) {
    this.ajaxfunc({'action': 'evaluate-xpath',
                   'session-id': this.session_id,
                   'xpath': xpath},
      function (resp) {
        callback(resp.output, resp.status);
      });
  };

  this.newRepeat = function(repeat) {
    this.ajaxfunc({'action': 'new-repeat',
                   'session-id': this.session_id,
                   'ix': getIx(repeat)},
      function (resp) {
          $.publish('adapter.reconcile', [resp, repeat]);
      },
      true);
  }

  this.deleteRepeat = function(repetition) {
    var juncture = getIx(repetition.parent);
    var rep_ix = +(repetition.rel_ix().split(":").slice(-1)[0]);
    this.ajaxfunc({'action': 'delete-repeat',
                   'session-id': this.session_id,
                   'ix': rep_ix,
                   'form_ix': juncture},
      function (resp) {
          $.publish('adapter.reconcile', [resp, repetition]);
      },
      true);
  }

  this.submitForm = function(form) {
    var answers = {};
    var prevalidated = true;
    var accumulate_answers = function(o) {
      if (ko.utils.unwrapObservable(o.type) !== 'question') {
        $.each(o.children(), function(i, val) {
            accumulate_answers(val);
          });
      } else {
        if (o.isValid()) {
          answers[getIx(o)] = ko.utils.unwrapObservable(o.answer);
        } else {
          prevalidated = false;
        }
      }
    }
    accumulate_answers(form);

    var adapter = this;
    this.ajaxfunc({'action': 'submit-all',
                   'session-id': this.session_id,
                   'answers': answers,
                   'prevalidated': prevalidated},
      function (resp) {
        if (resp.status == 'success') {
          form.submitting();
          adapter.submitfunc(resp);
        } else {
          $.each(resp.errors, function(ix, error) {
              adapter.serverError(getForIx(form, ix), error);
            });
          alert('There are errors in this form; they must be corrected before the form can be submitted.');
        }
      },
      true);
  }

  this.switchLanguage = function(lang) {
    var adapter = this;
    this.ajaxfunc({'action': 'set-lang',
                   'session-id': this.session_id,
                   'lang': lang},
      function (resp) {
          $.publish('adapter.reconcile', [resp, lang]);
      });
  }

  this.serverError = function(q, resp) {
    if (resp["type"] == "required") {
      q.serverError("An answer is required");
    } else if (resp["type"] == "constraint") {
      q.serverError(resp["reason"] || 'This answer is outside the allowed range.');      
    }
  }
}

function submit_redirect(params, path, method) {
  // hat tip: http://stackoverflow.com/questions/133925/javascript-post-request-like-a-form-submit
  method = method || "post"; // Set method to post by default, if not specified.
  path = path || "";
  // The rest of this code assumes you are not using a library.
  // It can be made less wordy if you use one.
  var form = document.createElement("form");
  form.setAttribute("method", method);
  form.setAttribute("action", path);
  
  for(var key in params) {
    var hiddenField = document.createElement("input");
    hiddenField.setAttribute("type", "hidden");
    hiddenField.setAttribute("name", key);
    hiddenField.setAttribute("value", params[key]);
    
    form.appendChild(hiddenField);
  }
  // required for FF 3+ compatibility
  document.body.appendChild(form);
  form.submit();
}


// preloaders are deprecated -- for backwards compatibility
function init_preloaders(preloaders) {
    if (preloaders == null) {
	return null;
    }

    var preload_data = {};
    for (var type in preloaders) {
        var dict = preloaders[type];

        preload_data[type] = {};
        for (var key in dict) {
            var val = dict[key];

            // this special character indicates a server preloader, which 
            // we make a synchronous request for
            if (val && val.indexOf("<") === 0) {
                valback = jQuery.ajax({url: PRELOADER_URL, type: 'GET', data:{"param": val}, async: false}).responseText;
                preload_data[type][key] = valback;
            } else {
                preload_data[type][key] = val
            }
        }
    }
    return preload_data;
}
