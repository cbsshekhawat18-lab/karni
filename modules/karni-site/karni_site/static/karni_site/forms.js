/*
 * karni-site: {% karni_form %} submitted in place.
 *
 * The form works without this file: it posts to karni_site's form view, which
 * redirects back with ?sent=<form> or renders the page again with the errors.
 * This script posts the same data with fetch, asks for JSON, and shows the
 * answer where the form is: the success message, each field's error next to
 * it, the rate-limit message. It is a static file from the site itself, with
 * no inline code, so it runs under Karni's Content-Security-Policy as it is.
 * Class names and texts come from the form's data-karni-* attributes, which the
 * tag fills from its arguments and settings.
 */
(function () {
  "use strict";

  if (!window.fetch || !window.FormData || !document.querySelectorAll) {
    return;
  }

  function classes(value) {
    return (value || "").split(/\s+/).filter(Boolean);
  }

  function addClasses(element, value) {
    classes(value).forEach(function (name) {
      element.classList.add(name);
    });
  }

  function removeClasses(element, value) {
    classes(value).forEach(function (name) {
      element.classList.remove(name);
    });
  }

  function controls(form, name) {
    return Array.prototype.filter.call(form.elements, function (element) {
      return element.name === name;
    });
  }

  function enhance(form) {
    if (form.getAttribute("data-karni-enhanced")) {
      return;
    }
    form.setAttribute("data-karni-enhanced", "true");
    var data = form.dataset;
    var status = form.querySelector("[data-karni-form-message]");
    var button = form.querySelector('[type="submit"]');

    function say(kind, text) {
      if (!status) {
        return;
      }
      removeClasses(status, data.karniSuccessClass);
      removeClasses(status, data.karniFailureClass);
      addClasses(status, kind === "success" ? data.karniSuccessClass : data.karniFailureClass);
      status.textContent = text;
      status.hidden = !text;
    }

    function clear() {
      Array.prototype.forEach.call(form.querySelectorAll("[data-karni-error]"), function (node) {
        node.parentNode.removeChild(node);
      });
      Array.prototype.forEach.call(form.querySelectorAll('[aria-invalid="true"]'), function (node) {
        node.removeAttribute("aria-invalid");
        removeClasses(node, data.karniInvalidClass);
        var described = (node.getAttribute("aria-describedby") || "")
          .split(/\s+/)
          .filter(function (id) {
            return id && !/-error$/.test(id);
          })
          .join(" ");
        if (described) {
          node.setAttribute("aria-describedby", described);
        } else {
          node.removeAttribute("aria-describedby");
        }
      });
    }

    function showErrors(errors) {
      var first = null;
      var loose = [];
      Object.keys(errors || {}).forEach(function (name) {
        var messages = [].concat(errors[name]).join(" ");
        var wrapper = name ? form.querySelector('[data-karni-field="' + name + '"]') : null;
        if (!wrapper) {
          loose.push(messages);
          return;
        }
        var id = wrapper.getAttribute("data-karni-field-id") + "-error";
        var note = document.createElement("p");
        note.id = id;
        note.setAttribute("data-karni-error", "");
        addClasses(note, data.karniErrorClass);
        note.textContent = messages;
        wrapper.appendChild(note);
        controls(form, name).forEach(function (control) {
          control.setAttribute("aria-invalid", "true");
          addClasses(control, data.karniInvalidClass);
          var described = control.getAttribute("aria-describedby");
          control.setAttribute("aria-describedby", described ? described + " " + id : id);
          first = first || control;
        });
      });
      if (first && first.focus) {
        first.focus();
      }
      return loose;
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      clear();
      say("", "");
      if (button) {
        button.disabled = true;
      }
      var token = form.querySelector('[name="csrfmiddlewaretoken"]');
      fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "X-CSRFToken": token ? token.value : "",
        },
      })
        .then(function (response) {
          return response
            .json()
            .catch(function () {
              return {};
            })
            .then(function (body) {
              return { code: response.status, body: body || {} };
            });
        })
        .then(function (result) {
          var body = result.body;
          var kind = body.status || (result.code === 429 ? "throttled" : "failed");
          if (body.ok) {
            if (data.karniFollow !== undefined && body.redirect) {
              window.location.assign(body.redirect);
              return;
            }
            form.reset();
            say("success", data.karniSuccess || body.message || "");
            return;
          }
          var loose = kind === "invalid" ? showErrors(body.errors) : [];
          var text = data["karni" + kind.charAt(0).toUpperCase() + kind.slice(1)];
          say("failure", [text || body.message || ""].concat(loose).join(" ").trim());
        })
        .catch(function () {
          say("failure", data.karniFailed || "");
        })
        .then(function () {
          if (button) {
            button.disabled = false;
          }
        });
    });
  }

  function start() {
    Array.prototype.forEach.call(document.querySelectorAll("form[data-karni-form]"), enhance);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
