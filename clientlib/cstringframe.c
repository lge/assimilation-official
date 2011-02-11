/**
 * @file
 * @brief Implements the @ref CstringFrame class - A frame for C-style null-terminated strings
 * @details CstringFrames are
 * All we really add is validation that they have exactly one zero, and that one at the end...
 *
 *
 * @author &copy; 2011 - Alan Robertson <alanr@unix.sh>
 * @n
 * Licensed under the GNU Lesser General Public License (LGPL) version 3 or any later version at your option,
 * excluding the provision allowing for relicensing under the GPL at your option.
 */
#include <string.h>
#include <projectcommon.h>
#include <frameset.h>
#include <cstringframe.h>
#include <frameformats.h>
#include <generic_tlv_min.h>
#include <tlvhelper.h>

FSTATIC gboolean _cstringframe_default_isvalid(Frame *, gconstpointer, gconstpointer);

///@defgroup CstringFrame CstringFrame class
/// Class for holding/storing C-style null-terminated strings
/// @{
/// @ingroup C_Classes

/// @ref CstringFrame 'isvalid' member function (checks for valid C-style string)
FSTATIC gboolean
_cstringframe_default_isvalid(Frame * self,	///< CstringFrame object ('this')
			      gconstpointer tlvptr,	///< Pointer to the TLV for this CstringFrame
			      gconstpointer pktend)	///< Pointer to one byte past the end of the packet
{
	gsize		length = get_generic_tlv_len(tlvptr, pktend);
	const guint8*	stringstart = get_generic_tlv_value(tlvptr, pktend);
	const guint8*	endplace = stringstart + length;
	const guint8*	expectedplace = endplace-1;

	g_return_val_if_fail(NULL != tlvptr, FALSE);
	g_return_val_if_fail(NULL != pktend, FALSE);
	g_return_val_if_fail(length >= 0,  FALSE);

	return expectedplace == memchr(stringstart, 0x00, length);
}


/// Construct a new CstringFrame - allowing for "derived" frame types...
/// This can be used directly for creating CstringFrame frames, or by derived classes.
CstringFrame*
cstringframe_new(guint16 frame_type,	///< TLV type of CstringFrame
	  gsize framesize)	///< size of frame structure (or zero for sizeof(CstringFrame))
{
	Frame*	baseframe;

	if (framesize < sizeof(CstringFrame)){
		framesize = sizeof(CstringFrame);
	}

	baseframe = frame_new(frame_type, framesize);
	baseframe->isvalid = _cstringframe_default_isvalid;
	proj_class_register_subclassed (baseframe, "CstringFrame");

	return CASTTOCLASS(CstringFrame, baseframe);
}
///@}
