
// IE compliance
if (!Array.prototype.indexOf) {
    Array.prototype.indexOf = function(e) {
	var ix = -1;
	for (var i = 0; i < this.length; i++) {
	    if (this[i] === e) {
		ix = i;
		break;
	    }
	}
	return ix;
    }
}


function WebFormSession(params) {
  if (params.form_uid) {
    this.form_spec = {type: 'uid', val: params.form_uid};
  } else if (params.form_content) {
    this.form_spec = {type: 'raw', val: params.form_content};
  } else if (params.form_url) {
    this.form_spec = {type: 'url', val: params.form_url};
  } 

  //note: the 'allow_html' params will open you up to XSS attacks if you have
  //forms that insert user-entered data into captions!

  this.instance_xml = params.instance_xml;
  this.session_data = params.session_data;

  this.onsubmit = params.onsubmit;
  this.onpresubmit = params.onpresubmit || function(){ return true; };

  // onload/onlanginfo
  this._onload = params.onload || function(adapter, response){};
  if (params.onlanginfo) {
      this.onload = function (adapter, response) {
          this._onload(adapter, response);
          if (response['langs'].length) {
              params.onlanginfo(function(lang) { adapter.switchLanguage(lang); }, response['langs']);
          }
      }
  } else{
      this.onload = this._onload;
  }

  this.onerror = params.onerror || function(resp){};

  this.urls = {
    xform: params.xform_url,
    autocomplete: params.autocomplete_url
  };

  this.load = function($div, $loading, init_lang) {
    this.$div = $div;
    this.$loading = $loading || $div.find('#loading');

    this.$div.addClass('webforms');

    var sess = this;
    var adapter = new xformAjaxAdapter(this.form_spec, this.session_data, this.instance_xml,
                                       function(p, cb, bl) { sess.serverRequest(p, cb, bl); },
                                       function(p) { sess.submit(p); },
                                       this.onpresubmit,
                                       {allow_html: params.allow_html}
                                       );
    adapter.loadForm($div, init_lang, this.onload, this.onerror);
  }

  this.submit = function(params) {
    this.inputActivate(false);
    this.inputActivate = function(){}; //hack to keep input fields disabled during final POST

    this.onsubmit(params.output);
  }

  this.serverRequest = function(params, callback, blocking) {
    var that = this;
    var url = that.urls.xform;
    this._serverRequest(
      function (cb) {
        jQuery.ajax(
            {type: "POST",
             url: url, 
             data: JSON.stringify(params), 
             success: cb, 
             dataType: "json",
             error: function (jqXHR, textStatus, errorThrown) { 
                console.log("Got an unexpected server error!", textStatus, errorThrown);
             }
        });
        
      },
      function (response) {
        // wrap the callback so we can catch generic errors and handle them
        if (response.status === "error") {
          that.onerror(response);
        } else {
          callback(response);
        }
      },
      blocking
    );
  }

  this.BLOCKING_REQUEST_IN_PROGRESS = false;
  this.LAST_REQUEST_HANDLED = -1;
  this.NUM_PENDING_REQUESTS = 0;
  // makeRequest - function that takes in a callback function and executes an
  //     asynchronous request (GET, POST, etc.) with the given callback
  // callback - callback function for request
  // blocking - if true, no further simultaneous requests are allowed until
  //     this request completes
  this._serverRequest = function(makeRequest, callback, blocking) {
    if (this.BLOCKING_REQUEST_IN_PROGRESS) {
      return;
    }

    this.NUM_PENDING_REQUESTS++;
    this.$loading.show();
    $("input#submit").attr('disabled', 'disabled');

    if (blocking) {
      this.inputActivate(false); // sets BLOCKING_REQUEST_IN_PROGRESS
    }
    var sess = this;
    makeRequest(function (resp) {
        // ignore responses older than the most-recently handled
        if (resp.seq_id && resp.seq_id < sess.LAST_REQUEST_HANDLED) {
          return;
        }
        sess.LAST_REQUEST_HANDLED = resp.seq_id;

        try {
            callback(resp);
        } catch (err) {
            error_msg = "".concat(
                "Something unexpected went wrong on that request. ",
                "If you have problems filling in the rest of your form please submit an issue. ",
                "Technical Details: ", err
            );
            sess.onerror({message: error_msg});

        }
        if (blocking) {
          sess.inputActivate(true); // clears BLOCKING_REQUEST_IN_PROGRESS
        }

        sess.NUM_PENDING_REQUESTS--;
        if (sess.NUM_PENDING_REQUESTS == 0) {
          sess.$loading.hide();
          $("input#submit").removeAttr('disabled');
        }
      });
  }

  this.inputActivate = function(enable) {
    this.BLOCKING_REQUEST_IN_PROGRESS = !enable;
    this.$div.find('input').attr('disabled', enable ? null : 'true');
    this.$div.find('a').css('color', enable ? 'blue' : 'grey');
  }

}

function submit_form_post(xml) {
  submit_redirect({type: 'form-complete', output: xml});
}

function touchformsHeartbeat(url, online, offline) {
    $.get(url).done(function() {
        online();
    }).fail(function(resp) {
        if (resp.status == 0) {
            offline();
        } else {
            // even error responses show that the daemon is still alive
            online();
        }
    });
}

function runInterval(func, interval) {
    var timer = setInterval(function() {
        func(function() {
            clearInterval(timer);
        });
    }, 1000. * interval);
    // also run now without delay
    func(function() {
        clearInterval(timer);
    });
}