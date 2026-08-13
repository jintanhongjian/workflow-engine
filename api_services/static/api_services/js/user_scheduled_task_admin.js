(function () {
  function safeParseJSON(value, fallback) {
    try {
      return JSON.parse(value);
    } catch (e) {
      return fallback;
    }
  }

  function renderPrettyJSON(data) {
    return JSON.stringify(data || {}, null, 2);
  }

  function setupTaskParamBinding() {
    var taskNameField = document.getElementById('id_task_name');
    var schemaPreviewField = document.getElementById('id_task_param_schema_preview');
    var taskParamsField = document.getElementById('id_task_params');

    if (!taskNameField || !schemaPreviewField || !taskParamsField) {
      return;
    }

    var taskSpecs = safeParseJSON(taskNameField.getAttribute('data-task-specs') || '{}', {});

    function buildTemplate(params) {
      var template = {};
      params.forEach(function (param) {
        template[param.name] = param.required ? '' : param.default;
      });
      return template;
    }

    function applyTaskSpec(taskName, shouldOverwriteParams) {
      var spec = taskSpecs[taskName] || { params: [] };
      var params = spec.params || [];

      schemaPreviewField.value = renderPrettyJSON(params);

      if (shouldOverwriteParams) {
        var template = buildTemplate(params);
        taskParamsField.value = renderPrettyJSON(template);
      }
    }

    var previousTaskName = taskNameField.value;
    applyTaskSpec(previousTaskName, false);

    taskNameField.addEventListener('change', function (e) {
      var nextTaskName = e.target.value;
      var confirmed = window.confirm('切换任务将覆盖当前 task_params 为新任务参数模板，是否继续？');

      if (!confirmed) {
        taskNameField.value = previousTaskName;
        return;
      }

      applyTaskSpec(nextTaskName, true);
      previousTaskName = nextTaskName;
    });
  }

  document.addEventListener('DOMContentLoaded', setupTaskParamBinding);
})();
