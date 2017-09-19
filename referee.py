"""
Referee creates struct xrefs for decompiled functions
"""
import logging

import idaapi

# logging.basicConfig(level=logging.WARN)
logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger("referee")


def is_assn(t):
    return (
        t == idaapi.cot_asg or
        t == idaapi.cot_asgbor or
        t == idaapi.cot_asgxor or
        t == idaapi.cot_asgband or
        t == idaapi.cot_asgsub or
        t == idaapi.cot_asgmul or
        t == idaapi.cot_asgsshr or
        t == idaapi.cot_asgushr or
        t == idaapi.cot_asgsdiv or
        t == idaapi.cot_asgudiv or
        t == idaapi.cot_asgsmod or
        t == idaapi.cot_asgumod)


def is_incdec(t):
    return (
        t == idaapi.cot_postinc or  # = 53,  ///< x++
        t == idaapi.cot_postdec or  # = 54,  ///< x--
        t == idaapi.cot_preinc  or  # = 55,  ///< ++x
        t == idaapi.cot_predec)     # = 56,  ///< --x


def add_struct_xrefs(cfunc):
    class xref_adder_t(idaapi.ctree_visitor_t):
        def __init__(self, cfunc):
            idaapi.ctree_visitor_t.__init__(self, idaapi.CV_PARENTS)
            self.cfunc = cfunc
            self.xrefs = {}

        def find_addr(self, e):
            if e.ea != idaapi.BADADDR:
                ea = e.ea
            else:
                while True:
                    e = self.cfunc.body.find_parent_of(e)
                    if e is None:
                        ea = self.cfunc.entry_ea
                        break
                    if e.ea != idaapi.BADADDR:
                        ea = e.ea
                        break
            return ea

        def visit_expr(self, e):
            dr = idaapi.dr_R | idaapi.XREF_USER
            ea = self.find_addr(e)

            # We wish to know what context a struct usage occurs in
            # so we can determine what kind of xref to create. Unfortunately,
            # a post-order traversal makes this difficult.

            # For assignments, we visit the left, instead
            # Note that immediate lvalues will be visited twice,
            # and will be eronneously marked with a read dref.
            # However, it is safer to overapproximate than underapproximate
            if is_assn(e.op) or is_incdec(e.op):
                e = e.x
                dr = idaapi.dr_W | idaapi.XREF_USER

            # &x
            if e.op == idaapi.cot_ref:
                e = e.x
                dr = idaapi.dr_O | idaapi.XREF_USER

            # x.m, x->m
            if (e.op == idaapi.cot_memref or
                  e.op == idaapi.cot_memptr):
                moff = e.m

                # The only way I could figure out how
                # to get the structure/member associated with its use
                typ = e.x.type

                if e.op == idaapi.cot_memptr:
                    typ.remove_ptr_or_array()

                strname = typ.dstr()
                if strname.startswith("struct "):
                    strname = strname[len("struct "):]

                stid = idaapi.get_struc_id(strname)
                struc = idaapi.get_struc(stid)
                mem = idaapi.get_member(struc, moff)

                if struc is not None:
                    if (ea, stid) not in self.xrefs or dr < self.xrefs[(ea, stid)]:
                        self.xrefs[(ea, stid)] = dr
                        idaapi.add_dref(ea, stid, dr)
                        log.debug((" 0x{:X} \t"
                                   "struct {} \t"
                                   "{}").format(
                                   ea, strname, flags_to_str(dr)))

                    if mem is not None:
                        if (ea, mem.id) not in self.xrefs or dr < self.xrefs[(ea, mem.id)]:
                            self.xrefs[(ea, mem.id)] = dr
                            idaapi.add_dref(ea, mem.id, dr)
                            log.debug((" 0x{:X} \t"
                                       "member {}.{} \t"
                                       "{}").format(
                                       ea, strname,
                                       idaapi.get_member_name(mem.id),
                                       flags_to_str(dr)))

                else:
                    log.error(("failure from 0x{:X} "
                               "on struct {} (id: 0x{:X}) {}").format(
                               ea, strname, stid, flags_to_str(dr)))

            return 0

    adder = xref_adder_t(cfunc)
    adder.apply_to_exprs(cfunc.body, None)


def clear_struct_xrefs(cfunc):
    xb = idaapi.xrefblk_t()
    ok = xb.first_from(cfunc.entry_ea, idaapi.XREF_DATA)
    while ok:
        if xb.user == 1:
            idaapi.del_dref(cfunc.entry_ea, xb.to)
        ok = xb.next_from()


def callback(*args):
    if args[0] == idaapi.hxe_maturity:
        cfunc = args[1]
        mat = args[2]
        if mat == idaapi.CMAT_FINAL:
            log.debug("analyzing function at 0x{:X}".format(
                cfunc.entry_ea))
            clear_struct_xrefs(cfunc)
            add_struct_xrefs(cfunc)
    return 0


class Referee(idaapi.plugin_t):
    flags = idaapi.PLUGIN_HIDE
    comment = "Adds struct xref info from decompilation"
    help = ""

    wanted_name = "Referee"
    wanted_hotkey = ""

    def init(self):
        if not idaapi.init_hexrays_plugin():
            return idaapi.PLUGIN_SKIP

        idaapi.install_hexrays_callback(callback)
        log.info(("Hex-Rays version {} has been detected; "
                  "{} is ready to use").format(
                  idaapi.get_hexrays_version(), self.wanted_name))
        self.inited = True
        return idaapi.PLUGIN_KEEP

    def run(self, arg):
        # never called
        pass

    def term(self):
        if self.inited:
            idaapi.remove_hexrays_callback(callback)
            idaapi.term_hexrays_plugin()


def PLUGIN_ENTRY():
    return Referee()


def flags_to_str(num):
    match = []
    if num & idaapi.dr_R == idaapi.dr_R:
        match.append('dr_R')
        num ^= idaapi.dr_R
    if num & idaapi.dr_O == idaapi.dr_O:
        match.append('dr_O')
        num ^= idaapi.dr_O
    if num & idaapi.dr_W == idaapi.dr_W:
        match.append('dr_W')
        num ^= idaapi.dr_W
    if num & idaapi.dr_I == idaapi.dr_I:
        match.append('dr_I')
        num ^= idaapi.dr_I
    if num & idaapi.dr_T == idaapi.dr_T:
        match.append('dr_T')
        num ^= idaapi.dr_T
    if num & idaapi.XREF_USER == idaapi.XREF_USER:
        match.append('XREF_USER')
        num ^= idaapi.XREF_USER
    if num & idaapi.XREF_DATA == idaapi.XREF_DATA:
        match.append('XREF_DATA')
        num ^= idaapi.XREF_DATA
    res = ' | '.join(match)
    if num:
        res += ' unknown: 0x{:X}'.format(num)
    return res


def clear_output_window():
    idaapi.process_ui_action('msglist:Clear')
