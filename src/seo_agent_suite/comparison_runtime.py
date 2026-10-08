"""Conservative provenance for the existing site collector's callable path.

Source fingerprints recognize this method's implementation, not a binary or
security signature. Unknown/source-less wrappers fail closed. Defaults are
read from the actual invoked functions, never from mutable default constants.
This resolver may read installed Python source; the metadata builder does not.
"""
from __future__ import annotations

import __future__
import hashlib
import inspect
from html.parser import HTMLParser
from types import CodeType, FunctionType

# Reviewed collector source for ruleset revision 1. A changed implementation
# needs review of extraction/completeness semantics, not a guessed default.
_SOURCE = {
    "audit": "ee303758e9c4cfd278d163dad45541d071cbd67f42264b79ae9399b62db5ee26",
    "fetch": "52844f16605c1bddeec1ea3222df986a89507c0f85328b665fdbe4cccacb3815",
    "fetch_public_url": "854289bf5a5cab2a8747563b8e5302b230cdacbaa33cb6d9fd525455e60fba7f",
    "follow_public_http": "10add404fb73d5f22ac9934837d2580a885b8ef43b8ad77751076c7b6b9c3c4c",
    "request_public_url_once": "6af1a1c147edcd4cfbf9675a4bdeb650664bca518db40a853b46069bb9e9b689",
    "request_via_proxy": "1f3d1a59da2dd89a6c075c37d109c2ace5c50771e0a74255784946f1ee97242b",
    "default_request_headers": "a2110baf1169353f3a8b2e28264f10b9c1c3999b20a51bcfd5b1762f4ebcb4a5",
}


# Exact reviewed #57 + #38-default-bindings variant. Only its no-option
# invocation is represented by v1; active attempt allowances are not in scope.
_ATTEMPT_SOURCE = {
    "audit": "94249b2b00260a108f8382d2479b052195844d5a9acf6796856f3c6a9efd1a88",
    "fetch": "398e79db1babbeb3e395ff4422bc535033c9b9ee136722d778a8c8297666228b",
    "fetch_public_url": "ba13fa556a6012c0d8fa96dc81d2de4f72f75e0a7c6048d2100a11ae31844ee3",
    "follow_public_http": "daf0af608fea653f0411b8cfbc3c25090f99f0446ae97c6ae0971b0c35cb6b71",
    "request_public_url_once": "2e20b98b55889726064a96778be1b474c8837c6e5385c0ff4853650bc2315a03",
    "request_via_proxy": "a1e4a0e8515d767cb822d09eb76e5dff923a8cb47dbb438bd359955289481c3c",
    "default_request_headers": _SOURCE["default_request_headers"],
}
# Exact reviewed Q5 body-payload variant; only the no-option path is in v1.
_BODY_SOURCE = {
    "audit": "92fda58cadd9254a5e0711cb0e78ab3a30050607f2bccaeb85a0fbeebcbc744c",
    "fetch": "1e423bb8dbc58d806500324eed0913f2f5da8ffe07a4d8af28d9bdcd6512dc5a",
    "fetch_public_url": "c5317e56e08907d7714c13f5156d4978dbc51c85d655a76f5f6ad74d21f472bc",
    "follow_public_http": "096d7ec735add92a3d9d9651a5bd36ffef95cd71654b1bc5272615a1791e64fa",
    "request_public_url_once": "514e304b7113fedf2817dc6a7c976003d53f18d8c5c0b1fa71464ff8b6fc3251",
    "request_via_proxy": "50304abf9e4eb8b698648fc4bbf46b34c62e5e71e9550f2886777f8babcded34",
    "default_request_headers": "a2110baf1169353f3a8b2e28264f10b9c1c3999b20a51bcfd5b1762f4ebcb4a5"
}

# The five lexical checks depend on these actual extraction bindings.
_EXTRACTION_SOURCE = {
    "MetaParser": "ea0ea762b39c5a275f2e5f395bfa694ffec3f3cb5cdfbaac1c83d3201124fa8d",
    "first_meta": "f0599bbaff8d0b2a32444ec6e65c91a44f781ac8382f72e59caea0c352138b45",
    "first_link": "78a702dfcd444c6d7fd279ec2aff42d7086c65c7a46c265627fc422d50fdf0f5",
    "open_graph_evidence": "0e5aabcf014c26cb66e5e9528cc20874c3a565fd2dfc493547dcfcce1c21ab23",
    "encoded_resource": "ff894534189ac3cb430018f2de6cb07c39fea15488bc363f6c66a985d104c898",
}
# Local redaction changes can alter OG lexical presence. Standard-library
# internals are outside this reviewed collector recognition boundary.
_REDACTION_SOURCE = {
    "redact_url": "d0fe5c34475dbd367d43cb79c37d3a54d8187ff82337e29d294aceb4f350a908",
    "_strip_userinfo_heuristic": "6efec88d7fa15e38abf228b4b474665269ff3c877395e64e711721fdb7463406",
}
_MISSING = object()


def _code(value):
    if isinstance(value, CodeType):
        return (value.co_code, tuple(_code(c) for c in value.co_consts),
                value.co_names, value.co_varnames, value.co_freevars,
                value.co_cellvars, value.co_argcount, value.co_kwonlyargcount,
                value.co_posonlyargcount, value.co_flags)
    return value


def _known(function, name, sources=None):
    if not isinstance(function, FunctionType) and not (name == "MetaParser" and isinstance(function, type)):
        return False
    try:
        source = inspect.getsource(function)
        if hashlib.sha256(source.encode()).hexdigest() != (_SOURCE if sources is None else sources)[name]:
            return False
        module_source = "".join(inspect.findsource(function)[0])
        compiled = compile(module_source, "<known-site-method>", "exec",
                           flags=__future__.annotations.compiler_flag, dont_inherit=True)
        expected = next(c for c in compiled.co_consts if isinstance(c, CodeType) and c.co_name == name)
        if name == "MetaParser":
            # Pin the reviewed parser methods as executed, including rejecting
            # overrides of inherited entry points such as feed/close.
            # Python 3.14 emits annotation thunks alongside method code;
            # these are compiler metadata, not parser methods in vars(cls).
            methods = {c.co_name: c for c in expected.co_consts
                       if isinstance(c, CodeType) and c.co_name != "__annotate__"}
            actual = {key: value for key, value in vars(function).items()
                      if callable(value) or key in methods
                      or any(callable(vars(base).get(key)) for base in HTMLParser.__mro__)}
            flag = __future__.annotations.compiler_flag
            return (function.__bases__ == (HTMLParser,) and actual.keys() == methods.keys()
                    and all(isinstance(actual[key], FunctionType)
                            and _code(actual[key].__code__.replace(co_flags=actual[key].__code__.co_flags & ~flag))
                            == _code(code.replace(co_flags=code.co_flags & ~flag))
                            for key, code in methods.items()))
        # Ignore filename/line positions, but check executed code too: source
        # alone cannot recognize a function whose __code__ was substituted.
        actual = function.__code__
        # Future annotations are a module compiler flag, not callable behavior.
        flag = __future__.annotations.compiler_flag
        return _code(actual.replace(co_flags=actual.co_flags & ~flag)) == _code(expected.replace(co_flags=expected.co_flags & ~flag))
    except (OSError, TypeError, ValueError, SyntaxError, StopIteration, KeyError):
        return False


def _bound_default(function, parameter):
    # Read binding data directly: __signature__ / __wrapped__ can describe a
    # wrapper rather than the defaults Python actually supplies to this code.
    kw = function.__kwdefaults__ or {}
    if parameter in kw:
        value = kw[parameter]
    else:
        names = function.__code__.co_varnames[:function.__code__.co_argcount]
        defaults = function.__defaults__ or ()
        start = len(names) - len(defaults)
        if parameter not in names or names.index(parameter) < start:
            return _MISSING
        value = defaults[names.index(parameter) - start]
    return value


def _default(function, parameter):
    value = _bound_default(function, parameter)
    return value if type(value) is int else None


def resolve_site_runtime_policy(module, *, audit_options=_MISSING):
    """Return only settings verified on the actual invocation chain."""
    policy = {"timeout_seconds": None, "max_body_bytes": None, "max_redirects": None,
              "request_headers": {"User-Agent": None, "Accept": None}}
    # The CLI passes the same options mapping it actually supplies to audit.
    # No active or explicit limit options are represented by this contract.
    if audit_options is not _MISSING and (type(audit_options) is not dict or audit_options):
        return policy
    audit = getattr(module, "audit", None)
    body_variant = _known(audit, "audit", _BODY_SOURCE)
    attempt_variant = body_variant or _known(audit, "audit", _ATTEMPT_SOURCE)
    sources = _BODY_SOURCE if body_variant else _ATTEMPT_SOURCE if attempt_variant else _SOURCE
    audit_limits = ("max_http_attempts", "max_http_body_bytes") if body_variant else ("max_http_attempts",)
    budgets = ("budget", "body_budget") if body_variant else ("budget",)
    if attempt_variant and (audit_options is _MISSING
                            or any(_bound_default(audit, name) is not None for name in audit_limits)):
        return policy
    if not _known(audit, "audit", sources):
        return policy

    if not all(_known(audit.__globals__.get(name), name, _EXTRACTION_SOURCE)
               for name in _EXTRACTION_SOURCE):
        return policy

    open_graph = audit.__globals__["open_graph_evidence"]
    redact = open_graph.__globals__.get("redact_url")
    if not _known(redact, "redact_url", _REDACTION_SOURCE):
        return policy
    if not _known(redact.__globals__.get("_strip_userinfo_heuristic"),
                  "_strip_userinfo_heuristic", _REDACTION_SOURCE):
        return policy

    def known(function, name):
        return (_known(function, name, sources)
                and (not attempt_variant or name == "default_request_headers"
                     or all(_bound_default(function, parameter) is None for parameter in budgets)))
    fetch = audit.__globals__.get("fetch")
    if fetch is not getattr(module, "fetch", None) or not known(fetch, "fetch"):
        return policy
    policy["timeout_seconds"] = _default(fetch, "timeout")
    public = fetch.__globals__.get("fetch_public_url")
    if not known(public, "fetch_public_url"):
        return policy
    policy["max_body_bytes"] = _default(public, "max_body_bytes")
    follow = public.__globals__.get("follow_public_http")
    if not known(follow, "follow_public_http"):
        return policy
    policy["max_redirects"] = _default(follow, "max_redirects")
    request = follow.__globals__.get("request_public_url_once")
    if not known(request, "request_public_url_once"):
        return policy
    proxy = request.__globals__.get("request_via_proxy")
    if not known(proxy, "request_via_proxy"):
        return policy
    helper = request.__globals__.get("default_request_headers")
    if proxy.__globals__.get("default_request_headers") is not helper:
        return policy
    if not known(helper, "default_request_headers"):
        return policy
    headers = helper()
    policy["request_headers"] = {key: headers.get(key) for key in ("User-Agent", "Accept")}
    return policy
