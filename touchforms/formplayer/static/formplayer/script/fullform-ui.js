var Formplayer = {
    Utils: {},
    Const: {},
    ViewModels: {},
};
var markdowner = window.markdownit();


//if index is part of a repeat, return only the part beyond the deepest repeat
function relativeIndex(ix) {
    var steps = ix.split(',');
    var deepest_repeat = -1,
        i;
    for (i = steps.length - 2; i >= 0; i--) {
        if (steps[i].indexOf(':') != -1) {
            deepest_repeat = i;
            break;
        }
    }
    if (deepest_repeat == -1) {
        return ix;
    } else {
        var rel_ix = '-';
        for (i = deepest_repeat + 1; i < steps.length; i++) {
            rel_ix += steps[i] + (i < steps.length - 1 ? ',' : '');
        }
        return rel_ix;
    }
}

function getIx(o) {
    var ix = o.rel_ix();
    while (ix[0] == '-') {
        o = o.parent;
        if (!o || ko.utils.unwrapObservable(o.rel_ix) === undefined) {
            break;
        }
        if (o.rel_ix().split(',').slice(-1)[0].indexOf(':') != -1) {
            ix = o.rel_ix() + ',' + ix.substring(1);
        }
    }
    return ix;
}

function getForIx(o, ix) {
    if (ko.utils.unwrapObservable(o.type) === 'question') {
        return (getIx(o) == ix ? o : null);
    } else {
        for (var i = 0; i < o.children().length; i++) {
            var result = getForIx(o.children()[i], ix);
            if (result) {
                return result;
            }
        }
    }
}

function ixInfo(o) {
    var full_ix = getIx(o);
    return o.rel_ix + (o.isRepetition ? '(' + o.uuid + ')' : '') + (o.rel_ix != full_ix ? ' :: ' + full_ix : '');
}

function parse_meta(type, style) {
    var meta = {};

    if (type == "date") {
        meta.mindiff = style.before !== null ? +style.before : null;
        meta.maxdiff = style.after !== null ? +style.after : null;
    } else if (type == "int" || type == "float") {
        meta.unit = style.unit;
    } else if (type == 'str') {
        meta.autocomplete = (style.mode == 'autocomplete');
        meta.autocomplete_key = style["autocomplete-key"];
        meta.mask = style.mask;
        meta.prefix = style.prefix;
        meta.longtext = (style.raw == 'full');
    } else if (type == "multiselect") {
        if (style["as-select1"]) {
            meta.as_single = [];
            var vs = style["as-select1"].split(',');
            for (var i = 0; i < vs.length; i++) {
                var k = +vs[i];
                if (k != 0) {
                    meta.as_single.push(k);
                }
            }
        }
    }

    if (type == "select" || type == "multiselect") {
        meta.appearance = style.raw;
    }

    return meta;
}

/**
 * Base abstract prototype for Repeat, Group and Form. Adds methods to
 * objects that contain a children array for rendering nested questions.
 * @param {Object} json - The JSON returned from touchforms to represent the container
 */
function Container(json) {
    var self = this;
    self.fromJS(json);

    /**
     * Used in KO template to determine what template to use for a child
     * @param {Object} child - The child object to be rendered, either Group, Repeat, or Question
     */
    self.childTemplate = function(child) {
        return ko.utils.unwrapObservable(child.type) + '-fullform-ko-template';
    };
}

/**
 * Reconciles the JSON representation of a Container (Group, Repeat, Form) and renders it into
 * a knockout representation.
 * @param {Object} json - The JSON returned from touchforms to represent a Container
 */
Container.prototype.fromJS = function(json) {
    var self = this;
    var mapping = {
        caption: {
            update: function(options) {
                return options.data ? DOMPurify.sanitize(options.data.replace(/\n/g, '<br/>')) : null;
            }
        },
        caption_markdown: {
            update: function(options) {
                return options.data ? markdowner.render(options.data) : null;
            }
        },
        children: {
            create: function(options) {
                if (options.data.type === Formplayer.Const.QUESTION_TYPE) {
                    return new Question(options.data, self);
                } else if (options.data.type === Formplayer.Const.GROUP_TYPE) {
                    return new Group(options.data, self);
                } else if (options.data.type === Formplayer.Const.REPEAT_TYPE) {
                    return new Repeat(options.data, self);
                } else {
                    console.error('Could not find question type of ' + options.data.type);
                }
            },
            update: function(options) {
                if (options.target.pendingAnswer &&
                        options.target.pendingAnswer() !== Formplayer.Const.NO_PENDING_ANSWER) {
                    // There is a request in progress
                    if (Formplayer.Utils.answersEqual(options.data.answer, options.target.pendingAnswer())) {
                        // We can now mark it as not dirty
                        options.data.answer = _.clone(options.target.pendingAnswer());
                        options.target.pendingAnswer(Formplayer.Const.NO_PENDING_ANSWER);
                    } else {
                        // still dirty, keep answer the same as the pending one
                        options.data.answer = _.clone(options.target.pendingAnswer());
                    }
                }

                // Do not update the answer if there is a server error on that question
                if (ko.utils.unwrapObservable(options.target.serverError)) {
                    options.data.answer = _.clone(options.target.answer());
                }
                return options.target;
            },
            key: function(data) {
                return ko.utils.unwrapObservable(data.uuid) || ko.utils.unwrapObservable(data.ix);
            }
        }
    }
    ko.mapping.fromJS(json, mapping, self);
};

/**
 * Represents the entire form. There is only one of these on a page.
 * @param {Object} json - The JSON returned from touchforms to represent a Form
 */
function Form(json) {
    var self = this;
    json.children = json.tree;
    delete json.tree;
    Container.call(self, json);
    self.submitText = ko.observable('Submit');
    self.evalXPath = new Formplayer.ViewModels.EvaluateXPath();

    self.submitForm = function(form) {
        $.publish('formplayer.submit-form', self);
    };

    $.unsubscribe('adapter');
    $.subscribe('adapter.reconcile', function(e, response, element) {
        // TODO where does response status parsing belong?
        if (response.status === 'validation-error') {
            if (response.type === 'required') {
                element.serverError('An answer is required');
            } else if (response.type === 'constraint') {
                element.serverError(response.reason || 'This answer is outside the allowed range.');
            }
            element.pendingAnswer(Formplayer.Const.NO_PENDING_ANSWER);
        } else {
            response.children = response.tree;
            delete response.tree;
            if (element.serverError) { element.serverError(null); }
            self.fromJS(response);
        }
    });

    self.submitting = function() {
        self.submitText('Submitting...');
    };
}
Form.prototype = Object.create(Container.prototype);
Form.prototype.constructor = Container;

/**
 * Represents a group of questions.
 * @param {Object} json - The JSON returned from touchforms to represent a Form
 * @param {Object} parent - The object's parent. Either a Form, Group, or Repeat.
 */
function Group(json, parent) {
    var self = this;
    Container.call(self, json);

    self.parent = parent;
    self.rel_ix = ko.observable(relativeIndex(self.ix()));
    self.isRepetition = parent instanceof Repeat;
    if (json.hasOwnProperty('domain_meta') && json.hasOwnProperty('style')) {
        self.domain_meta = parse_meta(json.datatype, val);
    }

    if (self.isRepetition) {
        // If the group is part of a repetition the index can change if the user adds or deletes
        // repeat groups.
        self.ix.subscribe(function(newValue) {
            self.rel_ix(relativeIndex(self.ix()));
        });
    }

    self.deleteRepeat = function() {
        $.publish('formplayer.delete-repeat', self);
        $.publish('formplayer.dirty');
    };

}
Group.prototype = Object.create(Container.prototype);
Group.prototype.constructor = Container;

/**
 * Represents a repeat group. A repeat only has Group objects as children. Each child Group contains the
 * child questions to be rendered
 * @param {Object} json - The JSON returned from touchforms to represent a Form
 * @param {Object} parent - The object's parent. Either a Form, Group, or Repeat.
 */
function Repeat(json, parent) {
    var self = this;
    Container.call(self, json);

    self.parent = parent;
    self.rel_ix = ko.observable(relativeIndex(self.ix()));
    if (json.hasOwnProperty('domain_meta') && json.hasOwnProperty('style')) {
        self.domain_meta = parse_meta(json.datatype, val);
    }
    self.templateType = 'repeat';

    self.newRepeat = function() {
        $.publish('formplayer.new-repeat', self);
        $.publish('formplayer.dirty');
    };

}
Repeat.prototype = Object.create(Container.prototype);
Repeat.prototype.constructor = Container;

/**
 * Represents a Question. A Question contains an Entry which is the widget that is displayed for that question
 * type.
 * child questions to be rendered
 * @param {Object} json - The JSON returned from touchforms to represent a Form
 * @param {Object} parent - The object's parent. Either a Form, Group, or Repeat.
 */
function Question(json, parent) {
    var self = this;
    self.fromJS(json);
    self.parent = parent;
    self.error = ko.observable(null);
    self.serverError = ko.observable(null);
    self.rel_ix = ko.observable(relativeIndex(self.ix()));
    if (json.hasOwnProperty('domain_meta') && json.hasOwnProperty('style')) {
        self.domain_meta = parse_meta(json.datatype, val);
    }
    self.throttle = 200;

    // If the question has ever been answered, set this to true.
    self.hasAnswered = false;

    // pendingAnswer is a copy of an answer being submitted, so that we know not to reconcile a new answer
    // until the question has received a response from the server.
    self.pendingAnswer = ko.observable(Formplayer.Const.NO_PENDING_ANSWER);
    self.pendingAnswer.subscribe(function() { self.hasAnswered = true });
    self.dirty = ko.computed(function() {
        return self.pendingAnswer() !== Formplayer.Const.NO_PENDING_ANSWER;
    });
    self.clean = ko.computed(function() {
        return !self.dirty() && !self.error() && !self.serverError() && self.hasAnswered;
    });
    self.hasError = ko.computed(function() {
        return (self.error() || self.serverError()) && !self.dirty();
    });

    self.isValid = function() {
        return self.error() === null && self.serverError() === null;
    };

    self.is_select = (self.datatype() === 'select' || self.datatype() === 'multiselect');
    self.entry = getEntry(self);
    self.entryTemplate = function() {
        return self.entry.templateType + '-entry-ko-template';
    };
    self.afterRender = function() { self.entry.afterRender(); };

    self.onchange = _.throttle(function() {
        $.publish('formplayer.dirty');
        self.pendingAnswer(_.clone(self.answer()));
        $.publish('formplayer.answer-question', self);
    }, self.throttle);

    self.mediaSrc = function(resourceType) {
        if (!resourceType || !_.isFunction(Formplayer.resourceMap)) { return ''; }
        return Formplayer.resourceMap(resourceType);
    }
}

/**
 * Reconciles the JSON representation of a Question and renders it into
 * a knockout representation.
 * @param {Object} json - The JSON returned from touchforms to represent a Question
 */
Question.prototype.fromJS = function(json) {
    var self = this;
    var mapping = {
        caption: {
            update: function(options) {
                return options.data ? DOMPurify.sanitize(options.data.replace(/\n/g, '<br/>')) : null;
            }
        },
        caption_markdown: {
            update: function(options) {
                return options.data ? markdowner.render(options.data) : null;
            }
        },
    };

    ko.mapping.fromJS(json, mapping, self);
}


Formplayer.ViewModels.EvaluateXPath = function() {
    var self = this;
    self.xpath = ko.observable('');
    self.result = ko.observable('');
    self.success = ko.observable(true);
    self.evaluate = function(form) {
        var callback = function(result, status) {
            self.result(result);
            self.success(status === "success");
        };
        $.publish('formplayer.evaluate-xpath', [self.xpath(), callback]);
    };
}

/**
 * Used to compare if questions are equal to each other by looking at their index
 * @param {Object} e - Either the javascript object Question, Group, Repeat or the JSON representation
 */
var cmpkey = function(e) {
    var ix = ko.utils.unwrapObservable(e.ix);
    if (e.uuid) {
        return 'uuid-' + ko.utils.unwrapObservable(e.uuid);
    } else {
        return 'ix-' + (ix ? ix : getIx(e));
    }
}

/**
 * Given an element Question, Group, or Repeat, this will determine the index of the element in the set of
 * elements passed in. Returns -1 if not found
 * @param {Object} e - Either the javascript object Question, Group, Repeat or the JSON representation
 * @param {Object} set - The set of objects, either Question, Group, or Repeat to search in
 */
var ixElementSet = function(e, set) {
    return $.map(set, function(val) {
        return cmpkey(val);
    }).indexOf(cmpkey(e));
}

/**
 * Given an element Question, Group, or Repeat, this will return the element in the set of
 * elements passed in. Returns null if not found
 * @param {Object} e - Either the javascript object Question, Group, Repeat or the JSON representation
 * @param {Object} set - The set of objects, either Question, Group, or Repeat to search in
 */
var inElementSet = function(e, set) {
    var ix = ixElementSet(e, set);
    return (ix !== -1 ? set[ix] : null);
}


function scroll_pin(pin_threshold, $container, $elem) {
    return function() {
        var base_offset = $container.offset().top;
        var scroll_pos = $(window).scrollTop();
        var elem_pos = base_offset - scroll_pos;
        var pinned = (elem_pos < pin_threshold);

        $elem.css('top', pinned ? pin_threshold + 'px' : base_offset);
    };
}

function set_pin(pin_threshold, $container, $elem) {
    var pinfunc = scroll_pin(pin_threshold, $container, $elem);
    $(window).scroll(pinfunc);
    pinfunc();
}


/**
 * Compares the equality of two answer sets.
 * @param {(string|string[])} answer1 - A string of answers or a single answer
 * @param {(string|string[])} answer2 - A string of answers or a single answer
 */
Formplayer.Utils.answersEqual = function(answer1, answer2) {
    if (answer1 instanceof Array && answer2 instanceof Array) {
        return _.isEqual(answer1, answer2);
    } else if (answer1 === answer2) {
        return true;
    }
    return false;
};

/**
 * Initializes a new form to be used by the formplayer.
 * @param {Object} formJSON - The json representation of the form
 * @param {Object} resourceMap - Function for resolving multimedia paths
 * @param {Object} $div - The jquery element that the form will be rendered in.
 */
Formplayer.Utils.initialRender = function(formJSON, resourceMap, $div) {
    var form = new Form(formJSON);
    Formplayer.resourceMap = resourceMap;
    ko.cleanNode($div[0]);
    ko.applyBindings(form, $div[0]);
    return form;
};

Formplayer.Const = {
    GROUP_TYPE: 'sub-group',
    REPEAT_TYPE: 'repeat-juncture',
    QUESTION_TYPE: 'question',

    // Entry types
    STRING: 'str',
    INT: 'int',
    LONG_INT: 'longint',
    FLOAT: 'float',
    SELECT: 'select',
    MULTI_SELECT: 'multiselect',
    DATE: 'date',
    TIME: 'time',
    GEO: 'geo',
    INFO: 'info',

    // Note it's important to differentiate these two
    NO_PENDING_ANSWER: undefined,
    NO_ANSWER: null,
};
