def get_filter_params_pal(filter_params: dict) -> dict:
    new_filter_params = {**filter_params}

    # new_filter_params["video_bpf_low"] = 1400000
    # new_filter_params["video_bpf_high"] = 7000000
    # new_filter_params["video_bpf_order"] = 1

    return new_filter_params


def get_sys_params_pal(sys_params: dict) -> dict:
    new_sys_params = {**sys_params}

    new_sys_params["ire0"] = 4257143
    new_sys_params["hz_ire"] = 1600000 / 140.0

    return new_sys_params


def get_filter_params_ntsc(filter_params: dict) -> dict:
    new_filter_params = {**filter_params}

    # new_filter_params["video_bpf_low"] = 1400000
    # new_filter_params["video_bpf_high"] = 6500000

    return new_filter_params


def get_sys_params_ntsc(sys_params):
    new_sys_params = {**sys_params}

    new_sys_params["ire0"] = 4257143
    new_sys_params["hz_ire"] = 1600000 / 140.0

    return new_sys_params
